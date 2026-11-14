"""Disposable primary checkout + linked worktree, driven through the real CLIs.

Shared by the coordination-root acceptance tests. Nothing here touches the
project's own board: every path is under the test's tmp_path.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SOURCE_FILES = (
    "scripts/crew/workboard/coordination_root.py",
    "scripts/crew/workboard/message.py",
    "scripts/crew/workboard/board_io.py",
    "scripts/crew/workboard/message_receipts.py",
    "scripts/forge/gates/workboard_inbox.py",
    "scripts/forge/gates/workboard_inbox_hook.py",
    "scripts/crew/brief/startup_router.py",
    "scripts/crew/brief/commit.py",
    "scripts/crew/brief/coordination_barrier.py",
)
COPIED = ("scripts", "thomas", "agent_safety.toml", "pyproject.toml")
IGNORED = shutil.ignore_patterns(
    "__pycache__", "*.pyc", ".pytest_cache", "node_modules", "browser", "server", "_archived"
)
IDENTITY_PREFIXES = ("THOMAS_AGENT", "AGENT_", "CODEX_", "CLAUDE_AGENT", "GEMINI_AGENT", "THOMAS_PROJECT_ROOT")
COORDINATOR = ("coordinator-a1", "sess-coordinator-a1")
WORKER = ("worker-b2", "sess-worker-b2")
TASK_ID = "NATIVE-ROOT-1"
BOARD = """# Thomas Workboard (Active)

Last updated: 2026-09-12

## Task Manager
- none

## Agent Claims
- none

## Active Tasks
- none

## Issues / Blockers
- none

## Up For Grabs
- none

## Agent Message Traffic
- none
"""
# The worker's claim lives on ITS OWN checkout's board: claims do not move to the coordination root.
WORKER_CLAIM = f"- agent={WORKER[0]}; name=Worker; role=solo; parent=none; scope=unit; task={TASK_ID}"
WORKER_TASK = f"- task_id={TASK_ID}; agent={WORKER[0]}; scope=unit; summary=unit work; status=active"

# Runs in the linked worktree as the worker. It records which board the commit tool's P0 barrier
# read on every call and which gate commands it handed to the landing, then makes a real dry-run
# commit with only the inbox gates (the other gates judge repository state this disposable
# checkout does not have). One gate worker, so no slot is taken from the machine-wide pool.
BARRIER_PROBE = """
import os, sys
os.environ["THOMAS_COMMIT_GATE_WORKERS"] = "1"
sys.path.insert(0, sys.argv[1])
from scripts.crew.brief import commit
barrier, land = commit.coordination_barrier.require_clear_p0, commit.commit_attempts.land
def judged(board, **kwargs):
    print("barrier", os.path.normcase(str(os.path.abspath(board))))
    return barrier(board, **kwargs)
def landing(core, **kwargs):
    print("land", os.path.normcase(str(os.path.abspath(kwargs["workboard_path"]))))
    for name, command in kwargs["local_gate_commands"]:
        print("gate", name, " ".join(str(token) for token in command[1:]))
    return land(core, **kwargs)
commit.coordination_barrier.require_clear_p0, commit.commit_attempts.land = judged, landing
gates = [(name, command) for name, command in commit.LOCAL_GATE_COMMANDS if name.startswith("workboard_inbox")]
result = commit.commit_scoped_changes(message="unit", agent=sys.argv[2], dry_run=True, local_gate_commands=gates)
print("commit", result.ok, result.blocker_class, "|", result.message)
"""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True)
    return proc.stdout.strip()


def _build_checkouts(root: Path) -> tuple[Path, Path]:
    primary = root / "primary"
    primary.mkdir()
    for rel in COPIED:
        source = REPO / rel
        if not source.exists():
            continue
        target = primary / rel
        if source.is_dir():
            shutil.copytree(source, target, ignore=IGNORED)
        else:
            shutil.copy2(source, target)
    board = primary / "plans" / "thomas" / "WORKBOARD.md"
    board.parent.mkdir(parents=True)
    board.write_text(BOARD, encoding="utf-8")
    (primary / ".gitignore").write_text("runtime/\n__pycache__/\n", encoding="utf-8")
    _git(primary, "init", "-q", "-b", "main")
    _git(primary, "config", "user.email", "test@example.invalid")
    _git(primary, "config", "user.name", "test")
    _git(primary, "config", "core.autocrlf", "false")
    _git(primary, "add", "-A")
    _git(primary, "commit", "-q", "-m", "disposable coordination root")
    worktree = root / "worker-checkout"
    _git(primary, "worktree", "add", "-q", str(worktree), "-b", "worker-unit")
    return primary, worktree


def _claim_unit_work(worktree: Path) -> None:
    """The worker's claim and one changed file inside it, so a dry-run commit has something to judge."""
    board = worktree / "plans" / "thomas" / "WORKBOARD.md"
    text = board.read_text(encoding="utf-8")
    text = text.replace("## Agent Claims\n- none", f"## Agent Claims\n{WORKER_CLAIM}", 1)
    text = text.replace("## Active Tasks\n- none", f"## Active Tasks\n{WORKER_TASK}", 1)
    board.write_text(text, encoding="utf-8")
    (worktree / "unit").mkdir()
    (worktree / "unit" / "work.txt").write_text("unit work\n", encoding="utf-8")
    (worktree / "barrier_probe.py").write_text(BARRIER_PROBE, encoding="utf-8")


def _secret(session: str) -> str:
    return f"disposable-handoff-{session}"


def _bind(primary: Path, agent: str, session: str) -> None:
    """Bind ``agent`` to ``session`` at the coordination root.

    The child processes are not children of this process on every platform (a
    Windows venv's python.exe starts the real interpreter as ITS child), so the
    binding is proven the way a native handoff proves it: by the session's
    handoff secret, which every child process of the scenario carries.
    """
    from thomas.core import agent_presence_sessions

    agent_presence_sessions.register_session(
        repo_root=primary,
        session_id=session,
        agent_id=agent,
        pid=os.getpid(),
        launcher="pytest",
        handoff_secret=_secret(session),
    )


def _bare_env() -> dict[str, str]:
    """No identity or session sources at all; the caller names the agent explicitly."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(IDENTITY_PREFIXES)}
    env.pop("PYTHONPATH", None)
    return env


def _env_for(agent: str, session: str) -> dict[str, str]:
    from thomas.core import agent_session_identity

    env = _bare_env()
    env.update({"THOMAS_AGENT_ID": agent, "THOMAS_AGENT_SESSION_ID": session, "AGENT_SESSION_ID": session})
    env[agent_session_identity.ATTESTATION_SECRET_ENV] = _secret(session)
    return env


class _Run:
    """One fresh process; everything about it is retained in the artifact."""

    def __init__(self, record: list[dict[str, object]]) -> None:
        self.record = record

    def __call__(
        self,
        label: str,
        checkout: Path,
        script: str,
        *args: str,
        actor: tuple[str, str],
        stdin: str = "",
    ) -> tuple[int, str, str]:
        command = [sys.executable, str(checkout / script), *args]
        assert "--workboard" not in command, "the scenario never overrides the board per command"
        proc = subprocess.run(
            command,
            cwd=str(checkout),
            env=_env_for(*actor),
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
        self.record.append(
            {
                "label": label,
                "cwd": str(checkout),
                "command": command,
                "actor": actor[0],
                "session": actor[1],
                "exit_status": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
            }
        )
        return proc.returncode, proc.stdout, proc.stderr


def _json(stdout: str) -> dict[str, object]:
    """The message tool prints one JSON line; the router prints an indented document."""
    text = stdout.strip()
    if text.startswith("{"):
        return json.loads(text)
    lines = [line for line in stdout.splitlines() if line.startswith("{")]
    assert lines, f"no JSON in output:\n{stdout}"
    return json.loads(lines[-1])


def _receipts(primary: Path) -> list[Path]:
    store = primary / "runtime" / "coordination" / "inbox_receipts"
    return sorted(store.rglob("*.jsonl")) if store.exists() else []


def _lines(out: str, prefix: str) -> list[str]:
    return [line for line in out.splitlines() if line.startswith(prefix)]


def _norm(path: Path) -> str:
    return os.path.normcase(str(path))
