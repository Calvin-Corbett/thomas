"""A finished Thomas project that was never handed in is booked for its hand-in again: at start and every so often.

On 2026-11-04 a finished project's hand-in crashed before it wrote any hold row. Nothing could move it on: "hand in
again" refuses a change that was never handed in, a reply in its chat is an answer and starts nothing, and the next
server start did not look at it. The change it made sat in its green for good.

Now :func:`book_unsettled` looks through this server's greens when the park loop starts and every ``SCAN_EVERY_S``
after. A project whose finished turn would still be handed in (``hand_in_hold.still_current``: its last turn is a
finished run's, it is not settled, stopped, steered or running, and Autopilot would settle it), whose runs changed
files, and that has no hold row, is booked ``held`` and due now. :mod:`thomas.server.autopilot_hold_tick` then tries
it like any held change: through ``_settle_thomas_project`` and ``settle_if_finished``, with the check before your
card and the second look. Nothing here hands anything in itself.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from thomas.server import green_checkout, hand_in_hold

log = logging.getLogger(__name__)
SCAN_EVERY_S = hand_in_hold.RETRY_S  # how often the greens are looked through after the first look at start
WHY = "it finished but was never handed in, so its hand-in is tried again"
_CONVERSATIONS = Path(".thomas") / "evolve" / "agent" / "conversations"
_last_scan: dict[str, float] = {}  # catalog -> when it was last looked through


def _changed_files(conversation: dict[str, Any]) -> bool:
    turns = conversation.get("turns") if isinstance(conversation.get("turns"), list) else []
    return any(isinstance(turn, dict) and turn.get("role") == "agent" and turn.get("changed_files") for turn in turns)


def unsettled(catalog: Path, *, app: Any = None) -> list[tuple[Path, str]]:
    """The greens' finished projects that would be handed in now and have no hold row: (green, conversation id)."""
    from thomas.server import self_change_status

    held = {str(item.get("cid") or "") for item in hand_in_hold.rows(catalog)}
    try:
        works = sorted(path for path in (green_checkout.green_root() / "work").iterdir() if path.is_dir())
    except OSError:  # no greens yet, or the folder cannot be listed: nothing to book this time
        return []
    found: list[tuple[Path, str]] = []
    for work in works:
        try:
            paths = sorted((work / _CONVERSATIONS).glob("*.json"))
        except OSError:
            continue
        for path in paths:
            cid = path.stem
            if cid in held or self_change_status.being_handed_in(cid):
                continue
            try:
                conversation = hand_in_hold.conversation_of(work, catalog, cid)
                if not conversation or not isinstance(conversation.get("thomas_project"), dict):
                    continue
                if _changed_files(conversation) and hand_in_hold.still_current(work, catalog, cid, None, app=app):
                    found.append((work, cid))
            except (
                OSError,
                ValueError,
                TypeError,
                KeyError,
                AttributeError,
            ) as exc:  # one project never stops the rest
                log.warning("could not tell whether Thomas project %s waits for its hand-in: %s", cid, exc)
    return found


def book_unsettled(app: Any, catalog: Path, port: int, *, startup: bool = False) -> list[str]:
    """Book each never-handed-in finished project ``held`` and due now; returns their conversation ids."""
    key, now = str(catalog), time.monotonic()
    if not port or (not startup and now - _last_scan.get(key, float("-inf")) < SCAN_EVERY_S):
        return []
    _last_scan[key] = now
    booked: list[str] = []
    for work, cid in unsettled(catalog, app=app):
        row = hand_in_hold.book(work, catalog, cid, port=port, claim_busy=True)  # held, due now, no try used
        if row is None or row.get("state") != "held":
            continue
        update = {**row, "step": "hand-in", "why": WHY}
        if hand_in_hold.change(catalog, cid, row["gen"], update, expected=row):
            log.warning("Thomas project %s finished but was never handed in; its hand-in is tried again", cid)
            booked.append(cid)
    return booked
