"""Subprocess entry point for one configured Forge Code turn.

The HTTP route stays the single run coordinator. This runner only adapts the
validated request to the existing Claude or AgentLoop dispatcher so exact GPT
model settings can be applied without rewriting project configuration.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import BinaryIO

from thomas.core.coding_agents import BUILTIN_AGENT_IDS, AgentRunRequest, builtin_registry

from .agent_passes import pass_for
from .forge_code_settings import (
    AUTONOMY_LEVELS,
    EXECUTION_MAX_FIX_ITERS,
    EXECUTION_TIMEOUTS_S,
    direct_shell_allowed,
)
from .forge_code_store import history_turns
from .forge_event_stream import FORGE_EVENT_KEY, _default_emit

_START_GATE_ENV = "THOMAS_CODE_START_GATE"
_START_GATE_TOKEN_ENV = "THOMAS_CODE_START_TOKEN"


@dataclass(frozen=True)
class StartGatePayload:
    """One-use parent release data received through the child's stdin pipe."""

    released: bool
    oauth_access_token: str = ""
    goal: str = ""
    candidate_root: str = ""
    source_root: str = ""


def read_start_gate(stream: BinaryIO | None = None) -> StartGatePayload:
    """Block until the parent records the run, then receive its live credential.

    The access token deliberately travels through the existing one-use stdin
    pipe. It never appears in process arguments, the environment, a transcript,
    or a temporary file.
    """
    if os.environ.get(_START_GATE_ENV) != "pipe":
        return StartGatePayload(released=True)
    token = os.environ.get(_START_GATE_TOKEN_ENV, "")
    if not token:
        return StartGatePayload(released=False)
    reader = stream if stream is not None else sys.stdin.buffer
    try:
        payload = json.loads(reader.readline().decode("utf-8"))
    except (OSError, RuntimeError, UnicodeDecodeError, json.JSONDecodeError):
        return StartGatePayload(released=False)
    if not isinstance(payload, dict):
        return StartGatePayload(released=False)
    supplied = str(payload.get("gate_token") or "")
    if not hmac.compare_digest(supplied, token):
        return StartGatePayload(released=False)
    binding = payload.get("self_edit") or {}
    if not isinstance(binding, dict):
        return StartGatePayload(released=False)
    return StartGatePayload(
        released=True,
        oauth_access_token=str(payload.get("oauth_access_token") or "").strip(),
        goal=str(payload.get("goal") or ""),
        candidate_root=str(binding.get("candidate_root") or ""),
        source_root=str(binding.get("source_root") or ""),
    )


def start_gate_released(stream: BinaryIO | None = None) -> bool:
    """Compatibility predicate for callers that only need the release state."""

    return read_start_gate(stream).released


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="thomas-forge-code-runner")
    parser.add_argument("goal", nargs="?", default="")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--conversation-id", default="")
    parser.add_argument("--history-root", default="")
    parser.add_argument("--engine", choices=("agent", "funnel"), default="agent")
    parser.add_argument("--family", choices=("claude", "gpt"), required=True)
    # Which agent runs, chosen apart from the model. Empty means a parent that
    # predates the picker, and gets the routing it had: GPT to Thomas's loop,
    # Claude to Claude Code.
    parser.add_argument("--agent", choices=("", *BUILTIN_AGENT_IDS), default="")
    parser.add_argument("--model", required=True)
    parser.add_argument("--profile", default="openai_codex")
    parser.add_argument("--autonomy", type=int, choices=AUTONOMY_LEVELS, default=3)
    parser.add_argument("--file-access", choices=("read_only", "workspace", "project", "pc", "full"), default="project")
    parser.add_argument("--memory", choices=("on", "off"), default="on")
    parser.add_argument("--guardrails", choices=("open", "guarded", "fortress"), default="guarded")
    parser.add_argument("--token-economy", choices=("cheap", "balanced", "max"), default="balanced")
    return parser


def run_configured_turn(args: argparse.Namespace, *, oauth_access_token: str = "") -> int:
    root = Path(args.project_root).resolve()
    history_root = Path(getattr(args, "history_root", "") or root).resolve()
    history = history_turns(history_root, str(args.conversation_id or "")) if args.memory == "on" else []
    live_edit = args.autonomy >= 3 and args.file_access != "read_only"
    # Direct shell follows direct_shell_allowed: Open permits the host shell, and
    # Guarded also permits a shell when this process runs as the cage account.
    # Fortress does not permit direct shell. Guarded shell access is bounded by
    # the cage account and its network fence; Open outside the cage leaves Claude's
    # Bash unsandboxed while the GPT tool path still confines it to selected paths.
    allow_shell = direct_shell_allowed(
        autonomy_level=args.autonomy,
        file_access=args.file_access,
        guardrails=args.guardrails,
    )
    timeout = EXECUTION_TIMEOUTS_S[args.token_economy]
    max_fix_iters = EXECUTION_MAX_FIX_ITERS[args.token_economy]
    definition = ""
    plan = ""
    if args.engine == "funnel":
        from .evolve_claude_bridge import compose_from_funnel

        try:
            definition, plan = compose_from_funnel(args.goal, project_root=root)
        except (RuntimeError, OSError, ValueError, TypeError) as exc:
            _default_emit(
                {
                    FORGE_EVENT_KEY: "error",
                    "text": f"Funnel planning failed before the build started: {exc}",
                }
            )
            return 1

    # The agent's own pass runs it. The one branch on the agent: Thomas on GPT takes
    # the profile the parent chose. No protected_paths are filled here yet, so
    # neither agent gets a protected-file fence from this runner.
    agent_id = str(getattr(args, "agent", "") or "") or ("thomas" if args.family == "gpt" else "claude_code")
    spec = builtin_registry().get(agent_id)
    launch = spec.plan(args.model)
    if agent_id == "thomas" and args.family == "gpt":
        launch = replace(launch, profile=args.profile)
    result = pass_for(spec)(
        AgentRunRequest(
            goal=args.goal,
            cwd=root,
            plan=launch,
            definition=definition,
            task_plan=plan,
            timeout=timeout,
            dry_run=not live_edit,
            max_fix_iters=max_fix_iters,
            history=history,
            file_access=args.file_access,
            guardrails=args.guardrails,
            autonomy_level=args.autonomy,
            token_economy=args.token_economy,
            allow_shell=allow_shell,
            oauth_access_token=oauth_access_token,
            allow_without_history=bool(getattr(args, "self_edit_bound", False)),
        )
    )

    _default_emit(
        {
            FORGE_EVENT_KEY: "meta" if result.ok or result.returncode == 75 else "error",
            "text": result.reason,
            "is_error": not result.ok and result.returncode != 75,
            **({"yielded_for_reload": True} if result.returncode == 75 else {}),
            # Distinguish the runner-owned verdict from ordinary progress/meta
            # events when the parent classifies a nonzero process exit.
            "terminal": True,
        }
    )
    if result.ok or result.returncode == 75:
        return int(result.returncode or 0)
    return int(result.returncode or 1)


def release_safe_path_for_children() -> None:
    """Stop PYTHONSAFEPATH at this process.

    The launcher sets it so this runner imports the Thomas that started it, not a
    copy of Thomas sitting in the project folder. sys.path is already fixed by the
    time this runs, so dropping the variable changes nothing here; it only keeps
    the checks this runner launches (pytest, import checks) from inheriting it,
    because they must import the project's own code."""
    os.environ.pop("PYTHONSAFEPATH", None)


def python_tools_on_path() -> None:
    """Put this runner's own environment (python, pytest, ruff) on PATH for the shell the agent gets.

    In the cage nothing else provides a Python, so a Build team with a shell could not run one test
    ("python: command not found", 2026-09-25). Appended, never prepended: where a project brings its own
    Python, that one still comes first."""
    scripts = str(Path(sys.executable).parent)
    parts = [part for part in os.environ.get("PATH", "").split(os.pathsep) if part]
    if scripts not in parts:
        os.environ["PATH"] = os.pathsep.join([*parts, scripts])


def handle_console_ctrl_c() -> bool:
    """Let what this runner starts handle a console Ctrl+C, while the runner itself ignores it. Windows only.

    The caged server ignores a console Ctrl+C (``scripts/cage/caged_server.py``) with the process-wide switch, and
    a child inherits that: on 2026-09-26, with every runner inheriting it, all six Build runs reached their team's
    final reply and then never finished. With the runner handling it instead, on 2026-09-27 each run -- by then on a
    console of its own -- was stopped with KeyboardInterrupt after its team's final reply. So the switch goes back on
    here, for the runner's children, and the runner ignores Ctrl+C through Python's own handler, which a child
    does not inherit.
    """
    if os.name != "nt":
        return False
    import ctypes
    import signal

    handled = bool(ctypes.windll.kernel32.SetConsoleCtrlHandler(None, False))
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    return handled


STACKS_EVERY_S = 1200.0


def record_stacks_while_running(logs_dir: Path | None = None, *, every_s: float = STACKS_EVERY_S) -> Path | None:
    """Every *every_s* seconds, write every thread's stack to ``<logs>/thomas.log.runner-<pid>.stacks``.

    Two Build runs went silent after their final reply on 2026-09-27 and stayed that way for an hour: no child
    process, no network connection, no CPU, and nothing said where they waited. The log export serves every
    ``thomas.log*`` file, so a runner that stalls leaves its stacks there. A runner that exits normally removes its
    file; one that is stopped or hangs keeps it.
    """
    import atexit
    import faulthandler
    import time

    from thomas.core.config import resolve_thomas_data_dir

    folder = Path(logs_dir) if logs_dir is not None else resolve_thomas_data_dir() / "logs"
    path = folder / f"thomas.log.runner-{os.getpid()}.stacks"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        handle = path.open("a", encoding="utf-8")
    except OSError:
        return None  # a runner without its stacks still runs
    handle.write(f"runner {os.getpid()} started {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n")
    handle.flush()
    faulthandler.dump_traceback_later(every_s, repeat=True, file=handle)

    def exited_cleanly() -> None:
        faulthandler.cancel_dump_traceback_later()
        handle.close()
        path.unlink(missing_ok=True)

    atexit.register(exited_cleanly)
    return path


def prepare_runner_process() -> None:
    """Set up this runner before any agent tool exists.

    Children must see the project's own code (``release_safe_path_for_children``),
    and runtime protection must guard the Thomas this runner loaded, not the
    project folder it works in, which may itself be a copy of Thomas."""
    import thomas
    from thomas.tools.filesystem import anchor_runtime_protection

    handle_console_ctrl_c()
    record_stacks_while_running()
    release_safe_path_for_children()
    python_tools_on_path()
    anchor_runtime_protection(Path(thomas.__file__).resolve().parents[1])


def configure_self_edit_runtime(project_root: Path) -> Path:
    """Keep memory, journals and runtime state outside both source trees."""
    from thomas.core.config import apply_runtime_data_env_defaults

    runtime_root = project_root.with_name(project_root.name + ".runtime")
    if runtime_root.resolve() != runtime_root:
        raise RuntimeError("Self-edit runtime directory redirects outside its assigned location")
    runtime_root.mkdir(parents=True, exist_ok=True)
    apply_runtime_data_env_defaults(base_dir=runtime_root, effective_dir=runtime_root, overwrite=True)
    os.environ.update(
        {
            "THOMAS_MEMORY_DATA_DIR": str(runtime_root),
            "THOMAS_MEMORY_ROOT": str(runtime_root / "runtime"),
            "THOMAS_MEMORY_PROFILE": "",
            "THOMAS_JOURNAL_DIR": str(runtime_root / "journal"),
            "PYTEST_ADDOPTS": "-p no:cacheprovider",
            "RUFF_CACHE_DIR": str(runtime_root / "ruff-cache"),
        }
    )
    return runtime_root


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    gate = read_start_gate()
    if not gate.released:
        return 75
    if gate.goal:
        args.goal = gate.goal
    if not args.goal:
        return 75
    if gate.candidate_root or args.history_root:
        if not (gate.candidate_root and gate.source_root and args.history_root):
            return 75
        candidate, source = Path(gate.candidate_root).resolve(), Path(gate.source_root).resolve()
        if (
            candidate != Path(args.project_root).resolve()
            or source != Path(args.history_root).resolve()
            or candidate == source
            or candidate.is_relative_to(source)
        ):
            return 75
        configure_self_edit_runtime(candidate)
        args.self_edit_bound = True
    return run_configured_turn(args, oauth_access_token=gate.oauth_access_token)


if __name__ == "__main__":
    # Process-wide setup belongs to the process that is the runner, not to main():
    # tests call main() inside the pytest process and must not inherit it.
    prepare_runner_process()
    sys.exit(main())
