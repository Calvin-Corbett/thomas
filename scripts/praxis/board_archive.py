"""Retention rule and archive format for the WORKBOARD message section.

Pure functions over bytes: no locks and no files. archive_io.py and
archive_board_messages.py do the I/O. The board is read as bytes and cut into
lines that keep their own terminators, so everything this module does not move
stays byte-exact.

Retention: a message row stays on the board when ANY of these holds.

  unparsed        the bullet is not a canonical message row (a reader reports it)
  open            nobody has acked it (inbox, audit, hook, takeover targets)
  open-p0         an unacked P0 row the stale rule would otherwise move. NEVER moved by the stale rule:
                  coordination_barrier.require_clear_p0 blocks an agent's commits while it has an open P0,
                  so archiving one would lift that block without anyone acking. The stale rule moves
                  p1, p2 and unprioritised rows only.
  recent          updated or created less than ``keep_days`` ago
  msg-referenced  the id appears elsewhere on the board
  plan-reference  newest row naming a `plans/thomas/*.md` file that nothing else on the
                  board names (plan_structure_gate wants every plan doc referenced)
  task-latest     newest row of each sender on a task that still has a live
                  claim, task, issue or problem row (its latest word stays)
  sender-latest   newest row of a sender that appears on the live board (the
                  idle sweep reads a claim holder's last message)
  last-row        it is the only row left (the section never goes empty)

Everything else is moved, in the original text, to a monthly append-only file.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from scripts.praxis.board_rows import (  # noqa: F401  (re-exported: callers import these from here)
    EOL_BYTES,
    EOL_NAMES,
    HEADING,
    KINDS,
    PLAN_REF,
    PRIORITIES,
    STATES,
    TERMINAL,
    TOKEN,
    _live_refs,
    _sole_plan_holders,
    _task_key,
    canonical_message,
    eol_of,
    find_section,
    parse_fields,
    parse_time,
    row_key,
    split_parts,
)


class ArchiveRefusal(RuntimeError):
    """The board is not in a shape this tool can move rows out of and back again."""


@dataclass(frozen=True)
class Moved:
    idx: int
    text: str
    key: str
    month: str
    stale_priority: str = ""  # set when the row was unacked and moved only because it is stale


@dataclass(frozen=True)
class Plan:
    moved: list[Moved]
    kept: dict[str, int]
    eol: str
    total: int


def make_plan(
    data: bytes,
    *,
    now: datetime,
    keep_days: float = 7.0,
    stale_open_days: float = 0.0,
) -> Plan:
    """Decide which message rows move. ``stale_open_days`` > 0 also moves old unacked rows."""
    lines = data.splitlines(keepends=True)
    section = find_section(lines)
    if section is None:
        raise ArchiveRefusal("the board has no `## Agent Message Traffic` section")
    tasks, agents, tokens, plans = _live_refs(lines, section)
    cutoff = now - timedelta(days=keep_days)
    open_cutoff = now - timedelta(days=stale_open_days) if stale_open_days > 0 else None
    rows = []  # (idx, fields, stamp)
    for idx in range(*section):
        fields = parse_fields(lines[idx].decode("utf-8", "replace")) if lines[idx].strip().startswith(b"- ") else None
        if fields is not None and not canonical_message(fields):
            fields = None
        stamp = parse_time(fields.get("updated_at") or fields["created_at"]) if fields else None
        rows.append((idx, fields, stamp))
    sole_plan = _sole_plan_holders(lines, rows, plans)
    newest: dict[str, datetime] = {}
    for _, fields, stamp in rows:
        if fields and stamp:
            sender = fields["from"].lower()
            for key in (sender if sender in agents else "", *_task_key(fields, tasks)):
                if key:
                    newest[key] = max(newest.get(key, stamp), stamp)
    kept: dict[str, int] = {}
    moved: list[Moved] = []
    eols: set[str] = set()
    bullets = [r for r in rows if lines[r[0]].strip().startswith(b"- ")]
    for idx, fields, stamp in bullets:
        reason = None
        if fields is None or stamp is None or parse_time(fields["created_at"]) is None:
            reason = "unparsed"
        elif fields.get("state", "open").lower() == "open" and (open_cutoff is None or stamp >= open_cutoff):
            reason = "open"
        elif fields.get("state", "open").lower() == "open" and fields.get("priority", "p1").lower() == "p0":
            reason = "open-p0"
        elif stamp >= cutoff:
            reason = "recent"
        elif fields["msg_id"] in tokens:
            reason = "msg-referenced"
        elif idx in sole_plan:
            reason = "plan-reference"
        elif any(stamp == newest.get(key) for key in _task_key(fields, tasks)):
            reason = "task-latest"
        elif stamp == newest.get(fields["from"].lower()):
            reason = "sender-latest"
        elif not eol_of(lines[idx]) or not _plain(lines[idx]):
            reason = "unparsed"
        if reason:
            kept[reason] = kept.get(reason, 0) + 1
            continue
        eols.add(EOL_NAMES[eol_of(lines[idx])])
        created = parse_time(fields["created_at"])
        text = lines[idx][: -len(eol_of(lines[idx]))].decode("utf-8")
        stale = fields.get("priority", "p1").lower() if fields.get("state", "open").lower() == "open" else ""
        moved.append(Moved(idx, text, fields["msg_id"], created.strftime("%Y-%m"), stale))
    if moved and len(moved) == len(bullets):
        kept["last-row"] = 1
        moved.pop()
    if len(eols) > 1:
        raise ArchiveRefusal(f"the board mixes line endings {sorted(eols)}; refusing to guess")
    return Plan(moved, kept, next(iter(eols), "lf"), len(bullets))


def _plain(raw: bytes) -> bool:
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def rows_digest(texts: list[str]) -> str:
    return hashlib.sha256("".join(t + "\n" for t in texts).encode("utf-8")).hexdigest()


def anchors_for(lines: list[bytes], moved: list[Moved]) -> list[tuple[int, str]]:
    """Runs of one month's rows: (offset in block, key of the line before the run)."""
    members = {m.idx for m in moved}
    runs: list[tuple[int, str]] = []
    for offset, item in enumerate(moved):
        before = item.idx - 1
        if offset and before == moved[offset - 1].idx:
            continue
        prev = lines[before] if before >= 0 else b""
        runs.append((offset, row_key(prev) if prev.strip().startswith(b"- ") and before not in members else "^"))
    return runs


def block_bytes(
    texts: list[str], keys: list[str], runs: list[tuple[int, str]], *, eol: str, at: str
) -> tuple[str, bytes]:
    """One archive block: header line, exact rows, manifest line. Returns (id, bytes)."""
    digest = rows_digest(texts)
    ident = hashlib.sha256((eol + json.dumps(runs) + digest).encode()).hexdigest()[:16]
    head = {"v": 1, "id": ident, "eol": eol, "runs": runs}
    tail = {"id": ident, "rows": len(texts), "first": keys[0], "last": keys[-1], "sha256": digest, "at": at}
    parts = [f"<!-- batch {json.dumps(head, separators=(',', ':'))} -->"]
    parts += texts
    parts.append(f"<!-- end-batch {json.dumps(tail, separators=(',', ':'))} -->")
    return ident, ("\n".join(parts) + "\n").encode("utf-8")


def stale_by_priority(moved: list[Moved]) -> dict[str, int]:
    """How many moved rows were unacked (moved by age alone), per priority."""
    counts: dict[str, int] = {}
    for item in moved:
        if item.stale_priority:
            counts[item.stale_priority] = counts.get(item.stale_priority, 0) + 1
    return counts
