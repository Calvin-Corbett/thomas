"""Row parsing and the live-board reference scan for the board archiver.

Pure functions over bytes and text, split out of board_archive.py to keep both files small.
board_archive.py re-exports every name here, so callers keep importing from board_archive.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

HEADING = b"agent message traffic"
STATES = {"open", "acked", "resolved"}
KINDS = {
    "coordination", "scope_change", "blocker", "handoff", "status", "decision",
    "ping", "brainstorm_call", "brainstorm_note", "brainstorm_decision",
}  # fmt: skip
PRIORITIES = {"p0", "p1", "p2"}
DECISIONS = {"none", "pending", "approved", "rejected"}
TERMINAL = {"done", "completed", "closed", "cancelled", "canceled", "resolved", "abandoned", "failed"}
TOKEN = re.compile(r"[A-Za-z0-9._-]+")
PLAN_REF = re.compile(r"`(plans/thomas/[^`]+\.md)`")  # the same reference plan_structure_gate reads
EOL_NAMES = {b"\r\n": "crlf", b"\n": "lf", b"\r": "cr"}
EOL_BYTES = {name: raw for raw, name in EOL_NAMES.items()}


def split_parts(token: str) -> list[str]:
    """Split ``k=v; k=v`` on semicolons that are not backslash-escaped."""
    parts: list[str] = []
    current: list[str] = []
    escaped = False
    for char in token:
        if escaped:
            current += ["\\", char]
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ";":
            if "".join(current).strip():
                parts.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if escaped:
        current.append("\\")
    if "".join(current).strip():
        parts.append("".join(current).strip())
    return parts


def parse_fields(text: str) -> dict[str, str] | None:
    """Fields of one ``- k=v; ...`` bullet, or None when it is not a field row."""
    stripped = text.strip()
    if not stripped.startswith("- "):
        return None
    fields: dict[str, str] = {}
    for part in split_parts(stripped[2:].strip()):
        key, sep, value = part.partition("=")
        key, value = key.strip().lower(), value.strip()
        if not sep or not key or not value:
            return None
        fields[key] = value
    return fields or None


def canonical_message(fields: dict[str, str] | None) -> bool:
    """True when message.py would load this row without complaint."""
    if not fields or any(not fields.get(k) for k in ("msg_id", "from", "to", "summary", "created_at")):
        return False
    low = {k: v.strip().lower() for k, v in fields.items()}
    return (
        low.get("state", "open") in STATES
        and low.get("kind", "coordination") in KINDS
        and low.get("priority", "p1") in PRIORITIES
        and low.get("decision", "none") in DECISIONS
    )


def parse_time(value: str) -> datetime | None:
    text = str(value or "").strip()
    text = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return (parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed).astimezone(timezone.utc)


def eol_of(line: bytes) -> bytes:
    for raw in (b"\r\n", b"\n", b"\r"):
        if line.endswith(raw):
            return raw
    return b""


def find_section(lines: list[bytes]) -> tuple[int, int] | None:
    """Body bounds of the message section, matching message.py's own search."""
    start: int | None = None
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith(b"## "):
            continue
        if start is None:
            if stripped[3:].strip().lower().startswith(HEADING):
                start = idx + 1
        else:
            return start, idx
    return None if start is None else (start, len(lines))


def row_key(line: bytes) -> str:
    fields = parse_fields(line.decode("utf-8", "replace"))
    if fields and fields.get("msg_id"):
        return fields["msg_id"]
    return "h:" + hashlib.sha1(line.strip()).hexdigest()[:16]


def _task_key(fields: dict[str, str], tasks: set[str]) -> tuple[str, ...]:
    task = fields["task_id"].lower()
    return (f"{fields['from'].lower()}|{task}",) if task in tasks else ()


def _live_refs(lines: list[bytes], section: tuple[int, int]) -> tuple[set[str], set[str], set[str], set[str]]:
    tasks: set[str] = set()
    agents: set[str] = set()
    tokens: set[str] = set()
    plans: set[str] = set()
    for idx, raw in enumerate(lines):
        if section[0] <= idx < section[1]:
            continue
        text = raw.decode("utf-8", "replace")
        tokens.update(TOKEN.findall(text))
        plans.update(PLAN_REF.findall(text))
        fields = parse_fields(text)
        if fields and fields.get("agent"):
            agents.add(fields["agent"].lower())
        if fields and fields.get("task_id"):
            if (fields.get("status") or fields.get("state") or "").lower() not in TERMINAL:
                tasks.add(fields["task_id"].lower())
    return tasks, agents, tokens, plans


def _sole_plan_holders(lines: list[bytes], rows: list, plans: set[str]) -> set[int]:
    """Index of the newest message row naming each plan file that no row outside the section names."""
    newest: dict[str, tuple[datetime, int]] = {}
    for idx, fields, stamp in rows:
        if not (fields and stamp):
            continue
        for ref in set(PLAN_REF.findall(lines[idx].decode("utf-8", "replace"))) - plans:
            if ref not in newest or stamp >= newest[ref][0]:
                newest[ref] = (stamp, idx)
    return {idx for _, idx in newest.values()}
