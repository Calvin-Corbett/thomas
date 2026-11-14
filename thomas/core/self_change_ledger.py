"""Every change Thomas makes to his own code, and how to take it back.

Owner direction, 2026-09-22: on Autopilot Thomas fixes his own blockers before
bringing them to you -- "obviously retractable ... then he gives a card ... at
the end of his reply like hey I had to change these things ... here's an undo
button here's an accept button to accept it forever ... you already made the
change fixed it and then you have to click on it to put it into stone".

So every write to Thomas's own code is recorded here with the exact bytes that
were there before it. :func:`undo` puts them back; :func:`accept` closes the
entry. Until you accept, nothing Thomas changed about himself is permanent.

On disk, under ``runtime/self_changes/``, because an undo has to survive the
restart that Thomas's own change may well cause. Each entry holds the whole
before and after text, so an undo never depends on a patch still applying.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_DIR_NAME = Path("runtime") / "self_changes"


def _dir(repo_root: str | Path | None = None) -> Path:
    from thomas.core.project_root import find_project_root

    root = Path(repo_root) if repo_root else find_project_root(Path.cwd())
    return root / _DIR_NAME


def record(
    *,
    path: str,
    before: str | None,
    after: str,
    why: str,
    task: str = "",
    chat: str = "",
    repo_root: str | Path | None = None,
) -> str:
    """Note one change to Thomas's own code. ``before`` is None for a new file."""
    entry_id = uuid.uuid4().hex[:12]
    folder = _dir(repo_root)
    folder.mkdir(parents=True, exist_ok=True)
    payload = {
        "id": entry_id,
        "path": str(path),
        "before": before,
        "after": after,
        "why": str(why or ""),
        "task": str(task or ""),
        "chat": str(chat or ""),
        "at": time.time(),
        "accepted": False,
        "undone": False,
    }
    (folder / f"{entry_id}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return entry_id


def _load(folder: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for file in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        try:
            rows.append(json.loads(file.read_text(encoding="utf-8")))
        # A half-written or hand-edited entry must not hide the others.
        except (OSError, ValueError):
            log.debug("unreadable self-change entry: %s", file, exc_info=True)
    return sorted(rows, key=lambda r: float(r.get("at") or 0))


def pending(task: str = "", repo_root: str | Path | None = None, *, chat: str = "") -> list[dict[str, Any]]:
    """Changes still waiting on you: not accepted, not undone.

    Narrowed by the run or the chat that made them, so one chat's card offers
    that chat's changes and not another's.
    """
    rows = [r for r in _load(_dir(repo_root)) if not r.get("accepted") and not r.get("undone")]
    if task:
        rows = [r for r in rows if str(r.get("task") or "") == str(task)]
    if chat:
        rows = [r for r in rows if str(r.get("chat") or "") == str(chat)]
    return rows


def _mark(entry_id: str, field: str, repo_root: str | Path | None) -> dict[str, Any] | None:
    file = _dir(repo_root) / f"{str(entry_id)}.json"
    try:
        row = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    row[field] = True
    file.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
    return row


def accept(entry_ids: list[str], repo_root: str | Path | None = None) -> int:
    """Keep these changes. They stop being offered for undo."""
    return sum(1 for entry_id in entry_ids if _mark(entry_id, "accepted", repo_root) is not None)


def undo(entry_ids: list[str], repo_root: str | Path | None = None) -> list[str]:
    """Put back exactly what was there before. Returns the paths restored.

    A file Thomas created is removed again. A file changed since is still
    restored: the owner asked for the change to be taken back, and the bytes
    recorded here are the ones they are taking it back to.
    """
    from thomas.core.project_root import find_project_root

    base = Path(repo_root) if repo_root else find_project_root(Path.cwd())
    restored: list[str] = []
    for entry_id in entry_ids:
        row = _mark(entry_id, "undone", repo_root)
        if row is None:
            continue
        target = base / str(row.get("path") or "")
        try:
            if row.get("before") is None:
                target.unlink(missing_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(str(row.get("before")), encoding="utf-8")
            restored.append(str(row.get("path") or ""))
        except OSError:
            log.warning("could not undo %s", row.get("path"), exc_info=True)
    return restored


__all__ = ["accept", "pending", "record", "undo"]
