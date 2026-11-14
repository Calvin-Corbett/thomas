#!/usr/bin/env python3
"""Durable read receipts for workboard messages.

WHY THESE EXIST. pre-commit clears unstaged changes before it runs any hook, by
checking the whole tree back out to the index. The board is a tracked file and
an ack never stages it, so for the ~40s of a commit every gate reading the board
sees the pre-ack copy and calls already-read mail unread. Measured three ways in
a scratch repo driving a real pre-commit: an ack in a tracked-but-unstaged file
is invisible to a hook, while the same ack under a gitignored path or in the
index survives.

WHY NOT JUST STAGE THE BOARD. Because `git add` from outside the commit process
mutates the index that pre-commit's own restore is anchored to. Its rollback
then checks out from an index that moved, its second `git apply` fails too, and
the exception escapes -- reverting UNRELATED files. That turns a coordination
fix into the data-loss bug scripts/forge/precommit_stash.py exists to clean up.
Worse, an ack re-serialises the WHOLE message section from the acking process's
parse; inside another agent's stash window that parse is of the reverted board,
so staging it would write everyone's rolled-back traffic into history.

So the receipt goes where the checkout cannot reach: runtime/, which .gitignore
excludes and which repo hygiene already forbids tracking. The board row stays
the source of truth for everyone else; the receipt is one agent's durable note
that it read the thing.

This module is storage only -- it never writes the board. Replaying a receipt
onto the board is `message.reconcile_receipts`, which lives there because it
needs the state machine and the lock. Keeping the two apart is what lets this
import nothing but board_io, so there is no cycle back into message.py.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from scripts.crew.workboard import board_io as _board_io


def _norm(value: str) -> str:
    return str(value or "").strip().lower()


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


RECEIPT_DIRNAME = "inbox_receipts"


def _receipts_path(workboard_path: Path, agent: str) -> Path:
    """Where one agent's receipts for ONE board live.

    Scoped to the board, not just the agent. Thomas runs a board per project
    root -- the repo's own, a data-dir board for one-off work -- and an agent id
    is reused across all of them, so an agent-only key lets an ack on one board
    silently mark a same-id message read on another. It also made every test
    that acks write into the real runtime/ directory and then poison the next
    test; that is how this was caught, in a batch that passed one file at a time.
    Resolved at call time so tests can redirect COORDINATION_DIR.
    """
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(agent or "").strip()) or "unknown"
    try:
        anchor = str(Path(workboard_path).resolve())
    except OSError:
        anchor = str(workboard_path)
    scope = hashlib.sha256(anchor.encode("utf-8", "replace")).hexdigest()[:12]
    return Path(_board_io.COORDINATION_DIR) / RECEIPT_DIRNAME / scope / f"{safe}.jsonl"


def _message_key(row: dict[str, object]) -> tuple[str, str]:
    """Identity of a message, not just its id.

    Keyed on created_at as well so a receipt can never suppress a DIFFERENT
    message that happens to carry the same id. Suppressing unread mail is the
    reassuring kind of wrong, which is the kind worth paying a field for.
    """
    return (_norm(str(row.get("msg_id", ""))), str(row.get("created_at", "")).strip())


def _write_receipt(workboard_path: Path, agent: str, row: dict[str, object], state: str) -> None:
    """Append one receipt. Callers must treat failure as survivable."""
    path = _receipts_path(workboard_path, agent)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "msg_id": str(row.get("msg_id", "")),
        "created_at": str(row.get("created_at", "")),
        "agent": str(agent),
        "state": str(state),
        "at": _now_iso(),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def _read_receipts(workboard_path: Path, agent: str) -> list[dict[str, object]]:
    """Every receipt this agent has written. Never raises: a receipt store that
    cannot be read means no receipts, which degrades to today's behaviour."""
    path = _receipts_path(workboard_path, agent)
    rows: list[dict[str, object]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return rows
    for line in text.splitlines():
        entry = line.strip()
        if not entry:
            continue
        try:
            parsed = json.loads(entry)
        except ValueError:
            continue          # a torn append is one lost receipt, not a broken inbox
        if isinstance(parsed, dict) and _norm(str(parsed.get("agent", ""))) == _norm(agent):
            rows.append(parsed)
    return rows


def _receipt_keys(workboard_path: Path, agent: str) -> set[tuple[str, str]]:
    receipts = _read_receipts(workboard_path, agent)
    return {(_norm(str(r.get("msg_id", ""))), str(r.get("created_at", "")).strip()) for r in receipts}


def reconcile(
    workboard_path: Path,
    *,
    agent: str,
    list_messages,
    set_state,
) -> list[str]:
    """Re-apply receipts the board no longer reflects; return the healed ids.

    A receipt only the recipient can see is half a fix. If the ack survives for
    this agent's gate but the board row stays open forever, then --inbox, the
    audit trail, the escalation clock and above all the SENDER are all told the
    message was never read.

    The two board operations arrive as arguments rather than as an import, so
    this module still depends on nothing but board_io. Deliberately never called
    from a gate read path: this writes, and a gate that writes is a gate that
    can fail for a new reason.
    """
    agent_clean = str(agent or "").strip()
    if not agent_clean:
        return []
    receipts = _read_receipts(workboard_path, agent_clean)
    if not receipts:
        return []
    ok, payload = list_messages(workboard_path, recipient=agent_clean, state="open")
    if not ok:
        return []
    still_open = {_message_key(row): row for row in payload.get("messages", [])}
    healed: list[str] = []
    for receipt in receipts:
        key = (_norm(str(receipt.get("msg_id", ""))), str(receipt.get("created_at", "")).strip())
        row = still_open.get(key)
        if row is None:
            continue
        good, _detail = set_state(
            workboard_path,
            msg_id=str(row.get("msg_id", "")),
            actor=agent_clean,
            state=str(receipt.get("state") or "acked"),
            record_receipt=False,
        )
        if good:
            healed.append(str(row.get("msg_id", "")))
    return healed


def filter_unread(payload: dict, workboard_path: Path, agent: str) -> dict:
    """Drop rows this agent already holds a receipt for."""
    seen = _receipt_keys(workboard_path, agent)
    if not seen:
        return payload
    rows = [row for row in payload.get("messages", []) if _message_key(row) not in seen]
    filtered = dict(payload)
    filtered["messages"] = rows
    filtered["message_count"] = len(rows)
    return filtered
