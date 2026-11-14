"""One project file that stays unreadable is skipped and named; it is not a wall in front of every other project.

On 2026-11-04 the Improve Thomas panel said "0 running; 0 queued. More cannot start: Thomas projects could not all be
read": a few conversation files raised PermissionError for the caged account on every scan, and any unreadable file
made the whole listing incomplete, so neither the automatic loop nor the Start button could start anything, ever.

Now a file that fails to read is retried: the next ``READ_ATTEMPTS - 1`` scans still report it as unreadable, which
keeps the listing incomplete as before (Windows refuses reads during a replace, so one failure says little). Once it
has failed ``READ_ATTEMPTS`` scans in a row it is *skipped*: named in the report's ``skipped`` list with its id and
why, and no longer in ``unreadable``. Callers using ``immediate=True`` skip identifiable project records and
project conversation folders on the first failure. A skipped green holds one project slot. Unidentified failures,
such as an unreadable overall inventory, remain blocking. Reasons name the failure kind, never file contents.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)
READ_ATTEMPTS = 3  # scans in a row that may fail to read one file before it is skipped
UNREADABLE = "unreadable"  # the state of a skipped green copy's row; it holds one project slot
_failures: dict[str, int] = {}
_lock = threading.Lock()


class Unread(str):
    """The sentence the listing shows for one unreadable file, carrying what is needed to skip it later."""

    key: str
    cid: str
    execution: str
    why: str
    where: str

    def __new__(cls, text: str, *, key: str, cid: str, execution: str, why: str, where: str = "green") -> Unread:
        made = super().__new__(cls, text)
        made.key, made.cid, made.execution, made.why, made.where = key, cid, execution, why, where
        return made


def why_of(exc: BaseException) -> str:
    strerror = getattr(exc, "strerror", None)
    return f"{type(exc).__name__}: {strerror}" if strerror else type(exc).__name__


def unread(path: Path, exc: BaseException, text: str, *, folder: bool = False) -> Unread:
    """``path`` is a conversation file (or, with ``folder``, a green's conversation folder) that could not be read."""
    path = Path(path)
    if folder:  # <green>/work/<execution>/.thomas/evolve/agent/conversations
        execution, cid = path.parents[3].name if len(path.parents) > 3 else path.name, ""
    else:
        cid = path.stem
        execution = path.parents[4].name if len(path.parents) > 4 else ""
    return Unread(text, key=str(path), cid=cid, execution=execution, why=why_of(exc))


def not_greens(entries: list[str]) -> None:
    """These came from handed-in copies or the registry, not from a team's working copy."""
    for entry in entries:
        if isinstance(entry, Unread):
            entry.where = "catalog"


def settle(entries: list[str], *, immediate: bool = False) -> tuple[list[str], list[dict[str, str]]]:
    """Split this scan's unreadable entries into those still being retried and those now skipped."""
    still: list[str] = []
    skipped: list[dict[str, str]] = []
    newly: list[Unread] = []
    with _lock:
        seen = {entry.key for entry in entries if isinstance(entry, Unread)}
        for key in [key for key in _failures if key not in seen]:
            del _failures[key]  # read fine this time (or gone): its count starts again
        for entry in entries:
            if not isinstance(entry, Unread):
                still.append(entry)
                continue
            _failures[entry.key] = _failures.get(entry.key, 0) + 1
            if not immediate and _failures[entry.key] < READ_ATTEMPTS:
                still.append(entry)
                continue
            if not immediate and _failures[entry.key] == READ_ATTEMPTS:
                newly.append(entry)
            execution = entry.execution if entry.where == "green" else ""
            skipped.append(
                {"id": entry.cid or execution, "execution_id": execution, "where": entry.where, "reason": entry.why}
            )
    for entry in newly:
        log.warning(
            "self-projects: %s %s could not be read in %d scans in a row (%s); skipped",
            entry.where,
            entry.cid or entry.execution,
            READ_ATTEMPTS,
            entry.why,
        )
    return still, skipped


def rows(skipped: list[dict[str, str]]) -> list[dict[str, Any]]:
    """A row for each skipped green copy: it may be a working project, so it is shown and holds a slot."""
    return [
        {
            "conversation_id": item["id"] if item["id"] != item["execution_id"] else "",
            "execution_id": item["execution_id"],
            "title": "",
            "chat_session_id": "",
            "state": UNREADABLE,
            "detail": (
                f"Its conversation could not be read ({item['reason']}), so it is skipped; "
                "it still holds one project slot until it can be read"
            ),
            "submission": "",
            "checked": "",
            "last_verdict": None,
            "changed_files": [],
            "updated_at": "",
        }
        for item in skipped
        if item["where"] == "green"
    ]


def _reset() -> None:
    """Tests only: forget every count."""
    with _lock:
        _failures.clear()
