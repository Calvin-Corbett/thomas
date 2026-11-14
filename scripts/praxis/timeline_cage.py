"""Read-only readers of the cage folder for the Praxis timeline: hand-ins, verdicts, second looks, promoter restarts.

Split from ``timeline_sources`` (the rest of what the timeline reads). Nothing here writes, makes a folder or asks a
server: it reads the folders the promoter and the second look write under the cage root (``THOMAS_CAGE_ROOT``).
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.praxis.timeline_sources import file_times, iso_to_epoch, read_json

_OUTBOX_NAME = re.compile(r"(self-.+)\.(pending|verdict)\.json$")
_PROMOTER_LINE = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),(\d{3}) pid=\d+ (.*)$")
_PROMOTER_EVENTS = (
    ("promoter started", "started"),
    ("promoter process exiting", "exiting"),
    ("stopped by an error", "crashed"),
)


def _record(path: Path) -> dict[str, Any]:
    """A JSON file the promoter wrote; empty if it is missing, unreadable or not a JSON object."""
    record = read_json(path)
    return record if isinstance(record, dict) else {}


def load_hand_ins(cage: Path) -> dict[str, dict[str, Any]]:
    """Every ``self-*`` submission in the inbox, processed and withdrawn folders, by submission id."""
    found: dict[str, dict[str, Any]] = {}
    for where in ("inbox", "processed", "withdrawn"):
        try:
            folders = sorted(path for path in (Path(cage) / where).glob("self-*") if path.is_dir())
        except OSError:
            continue
        for sub in folders:
            meta = _record(sub / "submission.json")
            found[sub.name] = {
                "sid": sub.name,
                "where": where,
                "execution_id": str(meta.get("execution_id") or ""),
                "submitted_at": meta.get("submitted_at"),
                "dir_mtime": (file_times(sub) or {}).get("modified"),
            }
    return found


def load_outbox(cage: Path) -> dict[str, dict[str, Any]]:
    """The promoter's ``<sid>.pending.json`` and ``<sid>.verdict.json`` records and their file times, by sid."""
    found: dict[str, dict[str, Any]] = {}
    for path in sorted((Path(cage) / "outbox").glob("self-*.json")):
        named = _OUTBOX_NAME.match(path.name)
        if named is None:
            continue
        sid, kind = named.groups()
        entry = found.setdefault(sid, {})
        entry[kind] = _record(path)
        entry[kind + "_times"] = file_times(path)
    return found


def _session(path: Path) -> dict[str, Any] | None:
    first = last = None
    verdict = ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        moment = iso_to_epoch(row.get("timestamp"))
        if moment is not None:
            first = moment if first is None else min(first, moment)
            last = moment if last is None else max(last, moment)
        if row.get("type") == "assistant":
            message = row.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            parts = content if isinstance(content, list) else []
            said = " ".join(str(c.get("text") or "") for c in parts if isinstance(c, dict) and c.get("type") == "text")
            if "NOT SAFE" in said or "NOT_SAFE" in said:
                verdict = "NOT SAFE"
            elif re.search(r"\bSAFE\b", said):
                verdict = "SAFE"
    if first is None:
        return None
    return {"session": path.stem, "start": first, "end": last, "verdict_text": verdict}


def load_second_looks(cage: Path) -> dict[str, list[dict[str, Any]]]:
    """The second look's Claude sessions (``precard/review.py`` runs in the team's green), by execution id."""
    found: dict[str, list[dict[str, Any]]] = {}
    for folder in sorted((Path(cage) / "claude" / "projects").glob("*-green-work-*")):
        execution = folder.name.split("-green-work-", 1)[1]
        for path in sorted(folder.glob("*.jsonl")):
            session = _session(path)
            if session is not None:
                found.setdefault(execution, []).append(session)
    for sessions in found.values():
        sessions.sort(key=lambda session: session["start"])
    return found


def promoter_restarts(cage: Path, since: float) -> list[dict[str, Any]]:
    """When the promoter started, exited or stopped on an error, at or after *since*: the time and the event only."""
    try:
        text = (Path(cage) / "promoter" / "promoter.log").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    events: list[dict[str, Any]] = []
    for line in text.splitlines():
        found = _PROMOTER_LINE.match(line)
        if found is None:
            continue
        try:
            local = datetime.strptime(found.group(1), "%Y-%m-%d %H:%M:%S").astimezone()
        except (ValueError, OverflowError, OSError):  # digits in the right places, but not a date this clock can place
            continue
        at = local.timestamp() + int(found.group(2)) / 1000
        event = next((name for words, name in _PROMOTER_EVENTS if words in found.group(3)), "")
        if event and at >= since:
            events.append({"at": round(at, 3), "event": event})
    return events


__all__ = ["load_hand_ins", "load_outbox", "load_second_looks", "promoter_restarts"]
