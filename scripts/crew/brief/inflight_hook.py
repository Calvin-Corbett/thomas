"""Claude Code hook: hold each file a session edits, so another session's commit cannot take its uncommitted lines.

Registered as a PostToolUse hook on Edit, Write, MultiEdit and NotebookEdit (.claude/settings.local.json). After each
edit it holds the file for the session's own process (scripts/crew/brief/inflight.py), and the hold ends when that
session commits the file or ends. When another live session also holds the file, the editing session is told at once,
so the two can sort it out before either is refused at commit time.

It never stands in the way of an edit: any failure is reported on stderr and the hook exits 0.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from subprocess import SubprocessError

import psutil

from scripts.crew.brief import git_reads, inflight

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


# git runs through the crew's one runner (git_reads.run_git): no console window, and inside the sandbox slot, which
# tests/test_every_command_runs_through_the_sandbox_slot.py holds every crew script to.
def _repo_of(path: Path) -> Path | None:
    done = git_reads.run_git(path.parent, ["rev-parse", "--show-toplevel"])
    top = done.stdout.decode("utf-8", "replace").strip()
    return Path(top) if done.returncode == 0 and top else None


def _ignored(root: Path, rel: str) -> bool:
    return git_reads.run_git(root, ["check-ignore", "-q", "--", rel]).returncode == 0


def handle(event: dict) -> str:
    """The hook's stdout for one PostToolUse event: '' or a JSON note for the session."""
    if event.get("tool_name") not in EDIT_TOOLS:
        return ""
    given = (event.get("tool_input") or {}).get("file_path") or (event.get("tool_input") or {}).get("notebook_path")
    if not given:
        return ""
    path = Path(given).resolve()
    root = _repo_of(path) if path.parent.is_dir() else None
    if root is None:
        return ""
    rel = path.relative_to(root.resolve()).as_posix()
    if rel.startswith(".git/") or _ignored(root, rel):
        return ""
    pid = inflight.session_pid()
    if pid is None:
        return ""
    session = str(event.get("session_id") or "")[:8]
    agent = os.environ.get("THOMAS_AGENT_ID") or "claude"
    inflight.hold(root, [rel], pid=pid, why=f"editing in Claude Code session {session}".strip(), agent=agent)
    others = inflight.held_by_others(root, [rel], me=pid)
    if not others:
        return ""
    note = (
        inflight.explain(others).split(". Committing now")[0]
        + ". You have now changed it too, so neither of you can commit it while both hold it: wait for that session to"
        " commit it, ask it to, or hand your lines over with `python -m scripts.crew.brief.inflight release --mine "
        + rel
        + "`."
    )
    return json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": note}})


def main() -> int:
    try:
        out = handle(json.loads(sys.stdin.read() or "{}"))
    # An edit must never fail because recording it did: say why on stderr and go on. These are what the hook can meet:
    # a malformed event (ValueError, TypeError, AttributeError), the disk or git (OSError, RuntimeError, SubprocessError),
    # a process that vanished mid-look (psutil.Error) and a held file outside the repository (ValueError from relative_to).
    except (ValueError, TypeError, AttributeError, OSError, RuntimeError, SubprocessError, psutil.Error) as exc:
        print(f"inflight hook: could not hold the edited file: {exc}", file=sys.stderr)
        return 0
    if out:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
