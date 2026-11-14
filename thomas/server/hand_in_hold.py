"""A finished change whose check, or second look, could not run waits on a durable record before your card.

Before this, a change whose check before your card could not run (too little disk, no interpreter, a scratch copy
of dev that could not be made, its deadline...) still reached your card marked "Not checked", and one whose second
look could not run was held only in memory, on an asyncio timer a restart forgot.

Now ``settle_if_finished`` raises ``precard.CheckUnavailable`` (or ``ReviewUnavailable``) instead, and the change
waits here: one row per conversation in :mod:`~thomas.server.hand_in_hold_store`, bound to the finished turn it was
made for (``gen``: the number of turns, the last turn's time and a hash of it). A row is only ever acted on while
that turn is still current (:func:`still_current`): not after your Stop, not while your steer waits for its run,
not once a newer run has written a turn. The route books the first try before its check starts (:func:`book`);
:mod:`thomas.server.autopilot_hold_tick` tries a held one again. Holds with inconclusive checks keep retrying, until
four checks in a row could not run: then the project pauses for you (``autopilot_enough``) and no try is scheduled;
other holds end with one recorded issue when their tries or strikes run out. Nothing about a hold lives only in memory.

States: ``checking`` (a try is running), ``held`` (waiting for its next try, read as "paused") and ``spent``
(read as "ended" until a new turn arrives).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from thomas.core.provider_limits import MAX_AHEAD_S, when_words
from thomas.server import autopilot_park, green_checkout
from thomas.server.hand_in_hold_store import NAME, change, check_claim, claim_free, read, row, rows, write

log = logging.getLogger(__name__)
RETRY_S = 900.0  # a held change is tried again this often at first (retry_after: then less often)...
MAX_TRIES = 96  # second looks without a prior dev-side failure stop after this many tries
RETRY_MAX_S = 7200.0  # the longest it waits between tries
MAX_STRIKES = 3  # those second looks also stop after this many costly failures
# An inconclusive check, including a dev-side failure, keeps retrying without a count limit.
CHECK_GRACE_S = 60.0  # after a restart, a check another boot was running is tried again this soon
clock = time.time  # module-local, so a test moves only this clock


def retry_after(tries: int) -> float:
    """How long a held change waits after its *tries*-th try: RETRY_S twice, then twice as long each time.

    A check that cannot finish was tried every 15 minutes, each try a full check: on 2026-10-27 one whose change
    selected 1,961 test files ran past its hour limit nine times in a day.
    """
    return min(RETRY_S * 2 ** min(max(int(tries) - 2, 0), 32), RETRY_MAX_S)


BOOT = uuid4().hex  # this server process; a "checking" row from another boot was interrupted by a restart


def generation(conversation: dict[str, Any]) -> list[Any]:
    """The finished turn a row is bound to: how many turns, the last one's time, and a hash of the last one."""
    turns = conversation.get("turns") if isinstance(conversation.get("turns"), list) else []
    last = turns[-1] if turns and isinstance(turns[-1], dict) else {}
    # A timestamp is optional and two turns may share one, so the exact finished turn is hashed too.
    encoded = json.dumps(last, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return [len(turns), str(last.get("ts") or ""), hashlib.sha256(encoded).hexdigest()]


class ConversationUnreadable(OSError):
    """The finished turn's conversation is there but could not be read: the change waits, it is not gone."""


def conversation_of(project_root: Path, catalog_root: Path, cid: str) -> dict[str, Any] | None:
    """The joined conversation as the hand-in reads it: earlier runs' transcripts cut to the tail any decision reads
    (``hand_in_hold_read``), the last turn whole. None when it is gone; ``ConversationUnreadable`` when it is there
    but cannot be read. Only the hand-in path reads this way: every other reader goes through the store as before."""
    from thomas.server import hand_in_hold_read
    from thomas.server.routes import evolve_agent_autopilot as route  # it imports this module

    path = Path(project_root) / ".thomas" / "evolve" / "agent" / "conversations" / f"{cid}.json"
    conversation = hand_in_hold_read.read(path)
    if conversation is None:
        why = hand_in_hold_read.last_failure(path)
        if why and path.is_file():
            raise ConversationUnreadable(f"its conversation could not be read ({why})")
        return None
    return route._joined(catalog_root, cid, conversation)


def still_current(
    project_root: Path, catalog_root: Path, cid: str, gen: list[Any] | None = None, *, app: Any = None
) -> bool:
    """Whether the booked finished turn may still be handed in: it is still the last turn, not settled, not
    stopped, with no steer waiting, no run going (when ``app`` is given), and Autopilot would still settle it."""
    from thomas.server import thomas_project
    from thomas.server.routes import evolve_agent_autopilot as route

    conversation = conversation_of(project_root, catalog_root, cid)
    if not conversation or not isinstance(conversation.get("thomas_project"), dict):
        return False
    if gen is not None and generation(conversation) != gen:
        return False
    turns = conversation.get("turns") or []
    if not turns or not isinstance(turns[-1], dict) or turns[-1].get("role") not in ("agent", "assistant"):
        return False
    if thomas_project.settled_record(catalog_root, cid):
        return False
    if thomas_project.stop_requested(conversation) or thomas_project.held_steers(cid):
        return False
    if app is not None:
        from thomas.server.routes.evolve_agent_run_state import APP_EVOLVE_AGENT_RUNS, slot_active

        if slot_active((app.get(APP_EVOLVE_AGENT_RUNS) or {}).get(cid)):
            return False
    return route._thomas_project_should_settle(route.decide(conversation), conversation)


def _keep_green(conversation: dict[str, Any], cid: str) -> None:
    """The green sweep run when a self-development Build session opens has no skip list: mark this one kept."""
    green = green_checkout.find_green(str((conversation.get("thomas_project") or {}).get("execution_id") or ""))
    if green is not None:
        green_checkout.mark_kept(green, f"the check before your card for Thomas project {cid} is waiting")


def book(
    project_root: Path,
    catalog_root: Path,
    cid: str,
    *,
    port: int = 0,
    chat: str = "",
    boot: str = "",
    gen: list[Any] | None = None,
    claim_busy: bool = False,
) -> dict[str, Any] | None:
    """Book the first try before the check starts (tries 1, due again in ``RETRY_S``), and return the row.

    The same turn booked twice returns the row already there. ``claim_busy`` (another hand-in of this conversation
    is running in this server) books it ``held`` and due now, without using a try. None when the turn is not
    current, so nothing may be handed in for it.
    """
    root, catalog = Path(project_root), Path(catalog_root)
    conversation = conversation_of(root, catalog, cid)
    if conversation is None:
        return None
    token = generation(conversation) if gen is None else gen
    if not still_current(root, catalog, cid, token):
        return None
    with autopilot_park._parks_lock(catalog):
        if not still_current(root, catalog, cid, token):
            return None
        found = read(catalog)
        old = next((item for item in found if item.get("cid") == cid), None)
        if old and old.get("gen") == token:
            return dict(old)
        project = conversation.get("thomas_project") if isinstance(conversation.get("thomas_project"), dict) else {}
        result = {
            "cid": cid,
            "project_root": str(root),
            "gen": token,
            "state": "held" if claim_busy else "checking",
            "tries": 0 if claim_busy else 1,
            "strikes": 0,
            "step": "check" if claim_busy else "",
            "why": "another hand-in is still using the check slot" if claim_busy else "",
            "next_at": clock() if claim_busy else clock() + RETRY_S,
            "port": int(port or 0),
            "chat": str(chat or project.get("chat_session_id") or cid),
            "boot": str(boot or BOOT),
        }
        write(catalog, [item for item in found if item.get("cid") != cid] + [result])
        try:
            _keep_green(conversation, cid)
        except (green_checkout.GreenUnavailable, OSError, ValueError):
            log.exception("could not mark the booked green of %s as kept", cid)
    return result


def drop(catalog_root: Path, cid: str, gen: list[Any] | None = None) -> bool:
    """Remove this turn's row; a newer turn's row is never removed."""
    return change(Path(catalog_root), cid, gen, None)


def retry_limited(row: dict[str, Any]) -> bool:
    """Only second looks without a prior dev-side failure have a retry count limit."""
    return row.get("step") == "second look" and not int(row.get("no_answers") or 0)


def hold(
    project_root: Path,
    catalog_root: Path,
    cid: str,
    step: str,
    why: str = "",
    *,
    costly: bool = True,
    no_answer: bool = False,
    port: int = 0,
    gen: list[Any] | None = None,
    expected: dict[str, Any] | None = None,
    until: float | None = None,
) -> dict[str, Any] | None:
    """A ``checking`` row waits for its next try (``held``), or ends (``spent``) once its tries or strikes run out.

    Only a costly failure uses one of the strikes: never too little disk. Checks retry without a count limit,
    even before a dev-side failure is recorded. Only second looks without a prior *no_answer* retain the caps.
    A row whose turn is no longer current is
    left as it is: the next tick removes it and starts any steer waiting for it. A second look refused by your plan's
    usage limit passes *until*, the reset: the row waits for it, not 900 s. A reset that is not ahead, or is further
    off than a reset is believed to be (31 days), is not used.
    """
    from thomas.server.issue_ledger import record_issue

    catalog = Path(catalog_root)
    observed = row(catalog, cid)
    token = gen if gen is not None else (observed or {}).get("gen")
    try:
        if token is None or not still_current(Path(project_root), catalog, cid, token):
            return None
    except ConversationUnreadable as exc:  # not proof the turn moved on: it waits, and is tried again
        step, why, costly, no_answer, until = "check", str(exc), False, False, None
    with autopilot_park._parks_lock(catalog):
        found = read(catalog)
        index = next((i for i, item in enumerate(found) if item.get("cid") == cid and item.get("gen") == token), None)
        if index is None or found[index].get("state") != "checking":
            return None
        if expected is not None and found[index] != expected:
            return None
        held = dict(found[index])
        strikes = int(held.get("strikes") or 0) + int(costly)
        no_answers = int(held.get("no_answers") or 0) + int(no_answer)
        spent = retry_limited({"step": step, "no_answers": no_answers}) and (
            int(held.get("tries") or 0) >= MAX_TRIES or strikes >= MAX_STRIKES
        )
        # The reset a usage limit named, when it is still ahead and no further than a reset is believed to be
        # (the bound the pause itself keeps); any other hold waits retry_after(tries), longer after each try.
        now = clock()
        resume = now + retry_after(int(held.get("tries") or 0))
        if until is not None and now < float(until) <= now + MAX_AHEAD_S:
            resume = float(until)
        held.update(
            state="spent" if spent else "held",
            strikes=strikes,
            no_answers=no_answers,
            step=str(step)[:120],
            why=str(why)[:2000],
            next_at=0 if spent else resume,
            port=int(port or held.get("port") or 0),
        )
        found[index] = held
        write(catalog, found)
    if spent:
        try:
            kind = "second_look_never_ran" if step == "second look" else "check_never_ran"
            message = f"Thomas project {cid}: {step} could not run ({why})"
            record_issue(
                surface="thomas_project",
                kind=kind,
                message=message,
                context={"conversation_id": cid, "step": str(step)[:120], "why": str(why)[:200]},
            )
        except (OSError, RuntimeError, ValueError):
            log.exception("could not record the spent hand-in of Thomas project %s", cid)
    return held


def _paused_for_you(root: Path, catalog: Path, cid: str, why: str, gen: list[Any] | None) -> bool:
    """Count this try's check that could not run; once enough came in a row, drop its row and say True."""
    from thomas.server import autopilot_enough  # it reaches this module through decide

    observed = row(catalog, cid) or {}
    token = gen if gen is not None else observed.get("gen")
    if token is None or observed.get("gen") != token or observed.get("state") != "checking":
        return False
    try:
        if not still_current(root, catalog, cid, token):
            return False
    except ConversationUnreadable:  # not proof of anything: the ordinary hold says why and tries again
        return False
    if not autopilot_enough.unavailable_stalled(root, catalog, cid, why, key=[token, observed.get("tries")]):
        return False
    drop(catalog, cid, token)
    return True


def hold_unavailable(
    project_root: Path, catalog_root: Path, cid: str, exc: Exception, *, gen: list[Any] | None = None
) -> dict[str, Any] | None:
    """:func:`hold` for a check or second look that could not run (``precard.ReviewUnavailable`` and its kinds).

    Its ``step``; ``costly`` (a usage limit is not: no strike); ``cause`` "dev-side", a check that gave no answer
    (retried without a count limit); and ``resets_at``, your plan's reset, which the hold waits for instead of 900 s.
    """
    step, why = getattr(exc, "step", "second look"), str(exc)
    costly, no_answer = getattr(exc, "costly", False), getattr(exc, "cause", "") == "dev-side"
    until = getattr(exc, "resets_at", None)
    if step == "check" and _paused_for_you(Path(project_root), Path(catalog_root), cid, why, gen):
        return None  # no further try: four checks in a row could not run, so it waits for you (autopilot_enough)
    return hold(project_root, catalog_root, cid, step, why, costly=costly, no_answer=no_answer, gen=gen, until=until)


RESTART_WAIT = "Thomas is restarting once the checks already running finish; this check starts after the restart"


def wait_for_restart(catalog_root: Path, cid: str, gen: list[Any] | None) -> bool:
    """A ``checking`` try whose check was not started because a restart is pending (``workers.Restarting``) waits.

    It gives its try back, takes no strike, is not counted as a check that could not run (so a restart never pauses a
    project, ``autopilot_enough``), and is due at once: the hold tick tries nothing while a restart is pending, so the
    try comes once the restart is over (the next server), or at once when the restart is cancelled.
    """
    catalog = Path(catalog_root)
    observed = row(catalog, cid)
    if gen is None or not observed or observed.get("gen") != gen or observed.get("state") != "checking":
        return False
    tries = max(0, int(observed.get("tries") or 0) - 1)
    waits = {**observed, "state": "held", "tries": tries, "step": "check", "why": RESTART_WAIT, "next_at": clock()}
    return change(catalog, cid, gen, waits, expected=observed)


def _still_current_snapshot(
    conversation: dict[str, Any] | None,
    cid: str,
    gen: list[Any] | None,
    catalog_conversation: dict[str, Any] | None,
) -> bool:
    """Apply still_current's checks to the already-read listing conversation."""
    from thomas.server import thomas_project
    from thomas.server.routes import evolve_agent_autopilot as route

    if not conversation or not isinstance(conversation.get("thomas_project"), dict):
        return False
    if gen is not None and generation(conversation) != gen:
        return False
    turns = conversation.get("turns") or []
    if not turns or not isinstance(turns[-1], dict) or turns[-1].get("role") not in ("agent", "assistant"):
        return False
    stored_project = (catalog_conversation or {}).get("thomas_project")
    if isinstance(stored_project, dict) and stored_project.get("settled_at"):
        return False
    if thomas_project.stop_requested(conversation) or thomas_project.held_steers(cid):
        return False
    return route._thomas_project_should_settle(route.decide(conversation), conversation)


def phase(
    project_root: Path,
    catalog_root: Path,
    cid: str,
    *,
    hold_rows: list[dict[str, Any]] | None = None,
    conversation: dict[str, Any] | None = None,
    catalog_conversation: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> tuple[str, str] | None:
    """What the project list and the chat card say while a row stands for the current turn; None otherwise."""
    catalog = Path(catalog_root)
    found = (
        row(catalog, cid)
        if hold_rows is None
        else next((dict(item) for item in hold_rows if item.get("cid") == cid), None)
    )
    if found is None:
        return None
    if hold_rows is None:
        try:
            if found.get("state") == "spent":
                conversation = conversation_of(Path(project_root), catalog, cid)
                if conversation is None or generation(conversation) != found.get("gen"):
                    return None  # you sent a message since: it carries on
            elif not still_current(Path(project_root), catalog, cid, found.get("gen")):
                return None
        except ConversationUnreadable:  # the row stands: what it says is shown until the conversation reads again
            pass
    else:
        # The listing supplies both snapshots; a vanished or unreadable green cannot have a current hold.
        if conversation is None:
            return None
        joined = {**conversation, "settings": (metadata or {}).get("settings") or {}}
        if found.get("state") == "spent":
            if generation(joined) != found.get("gen"):
                return None
        elif not _still_current_snapshot(joined, cid, found.get("gen"), catalog_conversation):
            return None
    step, why = str(found.get("step") or "check"), str(found.get("why") or "not completed")
    tries = int(found.get("tries") or 0)
    if found.get("state") == "spent":
        return (
            "ended",
            f"Never handed in: {step} could not run ({why}) after {tries} tries. Send a message and Thomas carries on",
        )
    if found.get("state") == "checking":
        from thomas.server.thomas_project_quiet import CHECKING

        return "waiting", CHECKING
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(float(found.get("next_at") or 0)))
    limit = f" of {MAX_TRIES}" if retry_limited(found) else ""
    words = (
        f"Held before your approval card: {step} could not run ({why}). "
        f"Tries again by himself {when} (try {tries}{limit})"
    )
    from thomas.server.precard import pause_shown  # late: precard is heavy, and holds for a check need none of it

    # Read without the ledger's lock, for display only: a steer reaches this on the event loop, and never waits.
    shown = pause_shown()
    if shown is not None and when_words(shown[0]) not in why:
        resume, estimated = when_words(shown[0]), shown[1]
        words += ". Second looks wait for your Claude plan's usage limit"
        # An estimate is a time Thomas works out to look again, not a reset he was told.
        words += f"; Thomas looks again {resume}" if estimated else f" until {resume}"
    return "paused", words


__all__ = [
    "BOOT",
    "ConversationUnreadable",
    "MAX_STRIKES",
    "MAX_TRIES",
    "NAME",
    "RETRY_S",
    "book",
    "change",
    "check_claim",
    "claim_free",
    "conversation_of",
    "drop",
    "generation",
    "hold",
    "hold_unavailable",
    "phase",
    "row",
    "rows",
    "still_current",
    "wait_for_restart",
]
