"""What the owner approved for Thomas's protected files, and how far it reaches.

Owner direction, 2026-09-22: "Every protected file needs to be its own thing."
And: "leave the option open, like would you like to approve just this task or
allow me to do whatever, because sometimes you work, you don't want to get
asked questions."

So the approval card offers three reaches, each behind one password:

* ``file`` -- this file, for the task that asked. The same task may write it
  again (an edit and then its fix) without asking twice; another file asks.
* ``task`` -- every protected file the task that asked goes on to touch.
* ``all``  -- every protected file, any task, until Thomas restarts or you
  revoke it.

Nothing is granted by time or by accident: a grant exists only because the
owner picked it on a card and Windows accepted their PIN or password. Held in
process memory on purpose -- a file on disk is something an agent with file
access could write; this process's memory is not.
"""

from __future__ import annotations

import threading
from typing import Any

SCOPE_FILE = "file"
SCOPE_TASK = "task"
SCOPE_ALL = "all"

_lock = threading.Lock()
_files: set[tuple[str, str]] = set()
_tasks: set[str] = set()
_everything = False


def _norm(path: str) -> str:
    return str(path or "").replace("\\", "/").strip().lower()


def allowed(task: str, path: str) -> bool:
    """True when an earlier approval already covers this write."""
    with _lock:
        if _everything:
            return True
        task = str(task or "")
        if task and task in _tasks:
            return True
        return bool(task) and (task, _norm(path)) in _files


def grant(scope: str, task: str, path: str) -> None:
    """Record an approval the owner made on a card (after the password check)."""
    global _everything
    task = str(task or "")
    with _lock:
        if scope == SCOPE_ALL:
            _everything = True
        elif scope == SCOPE_TASK and task:
            _tasks.add(task)
        elif scope == SCOPE_FILE and task:
            _files.add((task, _norm(path)))


def revoke_all() -> None:
    global _everything
    with _lock:
        _files.clear()
        _tasks.clear()
        _everything = False


def snapshot() -> dict[str, Any]:
    with _lock:
        return {"everything": _everything, "tasks": sorted(_tasks), "files": sorted(p for _, p in _files)}


__all__ = ["SCOPE_ALL", "SCOPE_FILE", "SCOPE_TASK", "allowed", "grant", "revoke_all", "snapshot"]
