"""The card at the end of the reply: here is what I changed about myself.

Owner direction, 2026-09-22: on Autopilot Thomas fixes his own blockers rather
than stopping to ask -- "you already made the change fixed it and then you have
to click on it to put it into stone". So when a run ends and Thomas has changed
his own code, the chat that asked gets a card naming each file and why, with
**Accept**, **Undo** and **Leave it for now**.

Undo restores the exact bytes from before each change
(thomas/core/self_change_ledger.py). Nothing here needs a password: the write
already passed the protected-file approval, and taking a change back is the
safe direction. Until you accept, a change stays listed and undoable.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from thomas.core import self_change_ledger
from thomas.core.user_questions import UserQuestionBook, question_book

log = logging.getLogger(__name__)

ACCEPT = "Accept"
UNDO = "Undo"
LATER = "Leave it for now"

# A card at the end of a run can wait a long time: the owner may be away. It is
# not holding a run open, so a day is cheap, and the entries stay listed anyway.
REVIEW_TIMEOUT_S = 24 * 60 * 60.0

_MAX_LISTED = 6


def summarize(changes: list[dict[str, Any]]) -> dict[str, Any]:
    """The card's body: what changed, and why."""
    fields = [
        {"label": str(c.get("path") or "a file"), "value": str(c.get("why") or "no reason recorded")}
        for c in changes[:_MAX_LISTED]
    ]
    extra = len(changes) - len(fields)
    note = f"{len(changes)} change(s) to Thomas's own code. Nothing is permanent until you accept."
    if extra > 0:
        note = f"{note} {extra} more not listed."
    return {"kicker": "Thomas changed his own code", "fields": fields, "note": note}


def offer(
    chat: str,
    *,
    book: UserQuestionBook | None = None,
    repo_root: str | Path | None = None,
    timeout_s: float = REVIEW_TIMEOUT_S,
) -> asyncio.Task[None] | None:
    """Show the chat what Thomas changed about himself, and act on the answer.

    Returns the task that settles the card, or None when there is nothing to
    review. Never raises: a run that did real work must not fail because the
    review card could not be posted.
    """
    if not str(chat or "").strip():
        return None
    active = book or question_book()
    try:
        changes = self_change_ledger.pending(repo_root=repo_root, chat=str(chat))
    except (OSError, ValueError):
        log.warning("could not read the self-change ledger", exc_info=True)
        return None
    if not changes:
        return None

    record = active.ask(
        question="Thomas changed his own code to get this done",
        options=[
            {"label": ACCEPT, "description": "Keep these changes."},
            {"label": UNDO, "description": "Put every file back exactly as it was."},
            {"label": LATER, "description": "Decide later. They stay listed and undoable."},
        ],
        session_id=str(chat),
        kind="card",
        details=summarize(changes),
    )
    entry_ids = [str(c.get("id") or "") for c in changes if c.get("id")]

    async def settle() -> None:
        try:
            answer = await active.wait_record(record, timeout_s=timeout_s)
        except (TimeoutError, asyncio.CancelledError):
            return  # still listed, still undoable
        chosen = (answer.get("selected") or [""])[0]
        try:
            if chosen == ACCEPT:
                await asyncio.to_thread(self_change_ledger.accept, entry_ids, repo_root)
            elif chosen == UNDO:
                restored = await asyncio.to_thread(self_change_ledger.undo, entry_ids, repo_root)
                log.warning("owner undid %d self-change(s): %s", len(restored), ", ".join(restored))
        except (OSError, ValueError):
            log.warning("could not settle the self-change review", exc_info=True)

    return asyncio.create_task(settle(), name=f"self-change-review:{record.id}")


__all__ = ["ACCEPT", "LATER", "REVIEW_TIMEOUT_S", "UNDO", "offer", "summarize"]
