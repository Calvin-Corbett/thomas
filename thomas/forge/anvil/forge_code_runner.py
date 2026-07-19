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
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from .dispatch_agent_loop import dispatch_via_agent_loop
from .dispatch_claude_cli import SAFE_CLI_TOOLS, dispatch_via_claude_cli
from .forge_code_settings import EXECUTION_MAX_FIX_ITERS, EXECUTION_TIMEOUTS_S
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
    return StartGatePayload(
        released=True,
        oauth_access_token=str(payload.get("oauth_access_token") or "").strip(),
        goal=str(payload.get("goal") or ""),
    )


def start_gate_released(stream: BinaryIO | None = None) -> bool:
    """Compatibility predicate for callers that only need the release state."""

    return read_start_gate(stream).released


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="thomas-forge-code-runner")
    parser.add_argument("goal", nargs="?", default="")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--conversation-id", default="")
    parser.add_argument("--engine", choices=("agent", "funnel"), default="agent")
    parser.add_argument("--family", choices=("claude", "gpt"), required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--profile", default="openai_codex")
    parser.add_argument("--autonomy", type=int, choices=(1, 2, 3, 4), default=3)
    parser.add_argument("--file-access", choices=("read_only", "workspace", "project", "pc", "full"), default="project")
    parser.add_argument("--memory", choices=("on", "off"), default="on")
    parser.add_argument("--guardrails", choices=("open", "guarded", "fortress"), default="guarded")
    parser.add_argument("--token-economy", choices=("cheap", "balanced", "max"), default="balanced")
    return parser


def run_configured_turn(args: argparse.Namespace, *, oauth_access_token: str = "") -> int:
    root = Path(args.project_root).resolve()
    history = history_turns(root, str(args.conversation_id or "")) if args.memory == "on" else []
    live_edit = args.autonomy >= 3 and args.file_access != "read_only"
    allow_shell = live_edit and args.guardrails == "open"
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

    if args.family == "gpt":
        result = dispatch_via_agent_loop(
            args.goal,
            cwd=root,
            definition=definition,
            plan=plan,
            profile=args.profile,
            timeout=timeout,
            dry_run=not live_edit,
            allow_shell=allow_shell,
            max_fix_iters=max_fix_iters,
            history=history,
            file_access=args.file_access,
            guardrails=args.guardrails,
            autonomy_level=args.autonomy,
            token_economy=args.token_economy,
            token_check=lambda: bool(oauth_access_token),
            oauth_access_token=oauth_access_token,
        )
    else:
        result = dispatch_via_claude_cli(
            args.goal,
            cwd=root,
            definition=definition,
            plan=plan,
            model=args.model,
            timeout=timeout,
            dry_run=not live_edit,
            allowed_tools=SAFE_CLI_TOOLS + (("Bash",) if allow_shell else ()),
            max_fix_iters=max_fix_iters,
            history=history,
            file_access=args.file_access,
            guardrails=args.guardrails,
            autonomy_level=args.autonomy,
        )

    _default_emit(
        {
            FORGE_EVENT_KEY: "meta" if result.ok else "error",
            "text": result.reason,
            "is_error": not result.ok,
        }
    )
    if result.ok:
        return int(result.returncode or 0)
    return int(result.returncode or 1)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    gate = read_start_gate()
    if not gate.released:
        return 75
    if gate.goal:
        args.goal = gate.goal
    if not args.goal:
        return 75
    return run_configured_turn(args, oauth_access_token=gate.oauth_access_token)


if __name__ == "__main__":
    sys.exit(main())
