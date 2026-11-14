"""The chat that asked for a self-fix sees its approval cards, and what happened.

The self-change promoter (scripts/cage/self_change_promoter.py) runs as you,
outside the server, and asks at the Windows sign-in. It writes each card to the
commit-master outbox before it asks. This follows those records and shows each
card in the chat that asked -- the same title, the same pairing code -- and then
the verdict. The card is a mirror, never the approval: it says so, and it has no
option that approves anything. The Windows prompt is where you approve.

Task 3b: reading a verdict also settles the green it is about
(:func:`verdict_arrived`, ``green_handoff.verdict_reached``): landed removes it,
anything else keeps it for 7 days and the card says where. The verdict card shows
the promoter's refusal word for word, with every conflicting file, and the mirror
waits as long as the chat's own card does (24 hours) for your answer.

Task 3g: a refusal only because the running copy has uncommitted work in the change's files
(:data:`RUNNING_COPY_DIRTY`) clears by itself once that work is committed. On 2026-09-25 four finished hand-ins were
refused that way within 20 minutes, and nothing tried again. :func:`wait_then_hand_in` waits until those files are clean
by the promoter's own test (``green_handoff.uncommitted_in_running_copy``), then hands the same green in again through
the settle path (:func:`hand_in_again`): a new submission, its verdict followed as usual, no repair round, no Build run.

That settle path now runs the check before your card, which can take up to an hour. So one hand-in again per
conversation is claimed (:func:`claim`) instead of holding a lock across it, and the route starts it in the background
(:func:`hand_in_again_later`) instead of inside its request.

One sign-in can list several self-fixes ("Yes, batch cards"): :mod:`thomas.server.self_change_cards` words each chat's
copy of that shared card, and says which card a landed change was approved on.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from thomas.core.kernel import late, seams
from thomas.server import self_change_cards

log = logging.getLogger(__name__)

_GOT_IT = [{"label": "Got it", "description": "Close this card. It does not approve or decline anything."}]
_VERDICTS = {
    "landed": "Your approval put this self-fix into the running Thomas",
    "declined": "You declined this self-fix, so nothing changed",
    "refused": "This self-fix was refused, and nothing changed",
    "error": "This self-fix could not be put into the running Thomas",
}


def outbox_dir() -> Path:
    from thomas.tools.cage_shell import cage_root

    return cage_root() / "outbox"


def _read(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


VERDICTS = _VERDICTS
# How the promoter begins a refusal because dev moved on under the change (scripts/cage/self_change_checks.py).
DEV_MOVED = "the change no longer applies to "
# How the promoter refuses a change whose files the running copy holds uncommitted work in (self_change_promoter.py).
RUNNING_COPY_DIRTY = "the running copy has uncommitted work in "
APPROVAL_WAIT_S = 24 * 3600.0
HAND_IN_POLL_S = 60.0  # between looks at the running copy, while a refused hand-in waits for it
HAND_IN_WAIT_S = 6 * 3600.0  # in all, from the first wait: a refusal of its own hand-in again waits within it


def dev_moved(verdict: dict[str, Any] | None) -> bool:
    """The promoter refused this change only because dev moved on under it: its team can merge dev and hand it in."""
    verdict = verdict or {}
    return verdict.get("status") == "refused" and str(verdict.get("detail") or "").startswith(DEV_MOVED)


def uncommitted_files(verdict: dict[str, Any] | None) -> list[str]:
    """The files the promoter named when it refused a change only because the running copy has uncommitted work in
    them (at most six: ``dirty[:6]``); [] for any other verdict. That refusal clears by itself once the work is
    committed."""
    verdict = verdict or {}
    first = next(iter(str(verdict.get("detail") or "").splitlines()), "")
    if verdict.get("status") != "refused" or not first.startswith(RUNNING_COPY_DIRTY):
        return []
    return [name.strip() for name in first[len(RUNNING_COPY_DIRTY) :].split(", ") if name.strip()]


def refusal_text(verdict: dict[str, Any] | None) -> str:
    """The promoter's words, whole, with every conflicting file it listed that its words do not already name."""
    verdict = verdict or {}
    detail = str(verdict.get("detail") or "")
    conflicts = [str(name) for name in verdict.get("conflicts") or [] if str(name) not in detail]
    return f"{detail}\nConflicting files: {', '.join(conflicts)}" if conflicts else detail


def verdict_arrived(verdict: dict[str, Any] | None, *, execution_id: str = "", sid: str = "") -> str:
    """Settle the green the verdict is about (``green_handoff.verdict_reached``); what the cards say about it, or ""."""
    from thomas.server import green_handoff

    try:
        return green_handoff.verdict_reached(verdict or {}, execution_id=execution_id, sid=sid)
    except (OSError, ValueError, TypeError, AttributeError):
        log.warning("could not act on the verdict for %s", (verdict or {}).get("submission_id"), exc_info=True)
        return ""


def read_verdict(sid: str, *, outbox: Path | None = None) -> dict[str, Any] | None:
    """The promoter's recorded verdict on submission *sid*, or None when it has not written one.

    For readers that also need to detect a withdrawn hand-in, use ``read_hand_in_state``.
    """
    return _read((outbox or outbox_dir()) / f"{sid}.verdict.json")


def read_hand_in_state(sid: str, *, outbox: Path | None = None) -> dict[str, Any] | None:
    """Read a verdict first; otherwise a hand-in moved to withdrawn was never asked about."""
    verdict = read_verdict(sid, outbox=outbox)
    if verdict is not None:
        return verdict
    from thomas.server import green_handoff

    if sid.startswith("self-") and (green_handoff.inbox_dir().parent / "withdrawn" / sid).is_dir():
        return {
            "submission_id": sid,
            "status": "withdrawn",
            "detail": "Withdrawn before your card: you were never asked.",
        }
    return None


def _show_card(book: Any, chat: str, card: dict[str, Any], checked: str = "") -> Any:
    # The Windows dialog's own wording comes from the pinned card catalogue (scripts/cage/card_catalogue.py,
    # whose SHA-256 lives in C:\ProgramData\ThomasPins), so the check's line rides this mirror card instead.
    fields, note = self_change_cards.card_fields(card)
    if checked:
        fields.append({"label": "Checked", "value": checked})
    return book.ask(
        question=str(card.get("title") or "Approve a self-fix"),
        options=_GOT_IT,
        session_id=chat,
        kind="card",
        details={
            "kicker": "Waiting for you at the Windows sign-in",
            "fields": fields,
            "pairing_code": str(card.get("pairing_code") or ""),
            "excerpt": str(card.get("excerpt") or ""),
            "note": note,
            "waits": False,
        },
    )


def _show_verdict(book: Any, chat: str, verdict: dict[str, Any], kept: str = "") -> str:
    status = str(verdict.get("status") or "error")
    fields = [{"label": "What happened", "value": refusal_text(verdict) or status}]
    if verdict.get("files"):
        fields.append({"label": "Files", "value": ", ".join(str(f) for f in verdict["files"])})
    if verdict.get("commit_sha"):
        fields.append({"label": "Commit", "value": str(verdict["commit_sha"])[:12]})
    place = self_change_cards.landed_on(verdict)
    if place:
        fields.append(place)
    if kept:
        fields.append({"label": "The change", "value": kept})
    book.ask(
        question=_VERDICTS.get(status, _VERDICTS["error"]),
        options=_GOT_IT,
        session_id=chat,
        kind="card",
        details={"kicker": "Thomas's self-fix", "fields": fields, "waits": False},
    )
    return status


async def follow(
    sid: str,
    chat: str,
    *,
    outbox: Path | None = None,
    book: Any | None = None,
    timeout_s: float = APPROVAL_WAIT_S,
    poll_s: float = 2.0,
    checked: str = "",
) -> str:
    """Mirror *sid*'s cards and verdict into *chat*. Returns the verdict's status,
    or "" if none arrived in time. Never raises: a card that could not be shown
    must not become a second failure of a run that already finished.

    ``checked`` is what the check before the card found (Task 3h, ``thomas.server.precard``); the mirror
    card shows it, so a card you are looking at says whether the change behind it was checked."""
    if not str(chat or "").strip():
        return ""
    try:
        if book is None:
            from thomas.core.user_questions import question_book

            book = question_book()
        box = outbox or outbox_dir()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        shown: dict[tuple[int, str], Any] = {}  # by place in the record and pairing code: a card rewritten there is new
        while loop.time() < deadline:
            state = read_hand_in_state(sid, outbox=box)
            if state is not None:
                for record in shown.values():
                    book.forget(record.id)
                if state.get("status") == "withdrawn":
                    return "withdrawn"
                kept = await asyncio.to_thread(verdict_arrived, state, sid=sid)
                return _show_verdict(book, chat, state, kept)
            record = _read(box / f"{sid}.pending.json")
            if record is None:  # not written yet, or caught unreadable: what is shown stays
                await asyncio.sleep(poll_s)
                continue
            asking = {
                (index, str(card.get("pairing_code") or "")): card
                for index, card in enumerate(record.get("cards") or [])
                if isinstance(card, dict) and card.get("state", "asking") == "asking"
            }
            for key in [key for key in shown if key not in asking]:
                book.forget(shown.pop(key).id)
            for key, card in asking.items():
                if key not in shown:
                    shown[key] = _show_card(book, chat, card, checked)
            await asyncio.sleep(poll_s)
    except (OSError, ValueError, TypeError, AttributeError):
        log.warning("could not follow self-fix %s", sid, exc_info=True)
    return ""


late.provide(seams.FOLLOW_SELF_CHANGE, lambda *args, **kwargs: follow(*args, **kwargs))


# -- Task 3g: a refusal that clears by itself hands the change in again ---------------------------------------------


@dataclass
class HandInWait:
    """A refused hand-in waiting for the running copy, in this server (a restart ends it: the route hands it in)."""

    sid: str  # the refused hand-in
    files: list[str]  # the files the running copy still had uncommitted work in, when last read
    since: float  # when the first wait of this chain began
    state: str = "waiting"  # "waiting" | "handed in" | "gave up"
    handed_in: str = ""  # the hand-in it made
    why: str = field(default="")  # why it gave up


_WAITS: dict[str, HandInWait] = {}  # by conversation
_waits_lock = threading.Lock()
# Conversations whose hand-in again is being checked and handed in right now: the waiter and the route never both
# hand in one refusal. A claim, not a lock held across the hand-in: the check before your card runs inside it and can
# take up to an hour, and a lock held that long made every other project's hand-in, and the route, wait for it.
_IN_FLIGHT: set[str] = set()
_hand_in_lock = threading.Lock()  # held only to claim, release and read the record: never across the check
_BACKGROUND: set[asyncio.Task[Any]] = set()  # hand-ins the route started, kept alive until they finish
_clock = time.time  # module-local, so a test moves only this clock
_sleep = asyncio.sleep


def active_hand_ins() -> dict[str, int]:
    """Count claims, background hand-ins, and waits still awaiting hand-in again."""
    with _hand_in_lock:
        claims = len(_IN_FLIGHT)
    background = len(_BACKGROUND)
    with _waits_lock:
        waits = sum(wait.state == "waiting" for wait in _WAITS.values())
    return {"claims": claims, "background": background, "waits": waits}


_TAKEN = "something else took it on since: a repair round, or it was handed in again already"
_BUSY = "it is already being checked and handed in again"


def claim(cid: str) -> bool:
    """Take the one hand-in again slot for this conversation; False when another hand-in has it."""
    with _hand_in_lock:
        if str(cid) in _IN_FLIGHT:
            return False
        _IN_FLIGHT.add(str(cid))
        return True


def release(cid: str) -> None:
    with _hand_in_lock:
        _IN_FLIGHT.discard(str(cid))


def being_handed_in(cid: str) -> bool:
    """A hand-in again of this conversation is being checked right now (the listing says so; send-back waits)."""
    with _hand_in_lock:
        return str(cid) in _IN_FLIGHT


def _again_url(cid: str) -> str:
    return f"/api/self/projects/{cid}/hand-in-again"  # self_project_routes.HAND_IN_AGAIN_PATH


def hand_in_wait(cid: str) -> HandInWait | None:
    with _waits_lock:
        return _WAITS.get(str(cid))


def _note(cid: str, sid: str, **changes: Any) -> None:
    """Change a conversation's wait: a hand-in again starts one when none waits on this refusal."""
    with _waits_lock:
        prior = _WAITS.get(cid)
        chained = prior is not None and sid in (prior.sid, prior.handed_in)
        wait = prior if chained and prior.sid == sid else HandInWait(sid, [], prior.since if chained else _clock())
        for name, value in changes.items():
            setattr(wait, name, value)
        _WAITS[cid] = wait


def hand_in_state(cid: str, sid: str, detail: str) -> tuple[str, str] | None:
    """The listing's state and words for a hand-in refused only for the running copy's uncommitted work: waiting for
    it, gave up and why, or that nothing waits and how to hand it in again. None for any other verdict."""
    files = uncommitted_files({"status": "refused", "detail": detail})
    if not files:
        return None
    if being_handed_in(cid):
        return "checking", "being checked before it is handed in again: its card comes once the check passes"
    wait = hand_in_wait(cid)
    if wait is not None and wait.sid == sid and wait.state == "waiting":
        return "waiting for the running copy", (
            f"refused only because the running copy has uncommitted work in {', '.join(wait.files or files)}: it is "
            f"handed in again once that work is committed (checked every {HAND_IN_POLL_S:g} s, for up to "
            f"{HAND_IN_WAIT_S / 3600:g} hours)"
        )
    if wait is not None and wait.sid == sid and wait.state == "gave up":
        return "refused", wait.why
    return "refused", (
        f"refused only because the running copy had uncommitted work in {', '.join(files)}, and nothing is waiting to "
        f"hand it in again in this server: once that work is committed, POST {_again_url(cid)} hands it in again"
    )


def _settle_again(project_root: Path, catalog_root: Path, cid: str, sid: str) -> tuple[Path | None, str]:
    """Hand the green in again, the way it was handed in first; the new submission, or None and why not.

    The caller holds this conversation's claim (:func:`claim`), so nothing else hands it in meanwhile."""
    from thomas.forge.anvil import forge_code_store
    from thomas.server import thomas_project

    record = thomas_project.settled_record(catalog_root, cid)
    if record is None or str(record.get("submission") or "") != sid:
        return None, _TAKEN
    submission = thomas_project.settle_if_finished(project_root, catalog_root, cid)  # the check runs in here
    if submission is None:
        return None, "the hand-off did not go out (the issue log and the server log say why)"
    stored = forge_code_store.load_conversation(catalog_root, cid) or {}
    if isinstance(stored.get("thomas_project"), dict):  # what the listing shows as the verdict before this one
        stored["thomas_project"]["handed_in_after"] = sid
        forge_code_store.write_conversation(catalog_root, stored)
    return submission, ""


async def hand_in_again(
    app: Any,
    project_root: Path,
    catalog_root: Path,
    cid: str,
    sid: str,
    *,
    fresh: bool = False,
    claimed: bool = False,
) -> tuple[str, str]:
    """Hand refused hand-in *sid*'s green in again at once, and follow the new hand-in's verdict as the first one's was
    (``evolve_agent_autopilot._follow_verdict``). The new submission id, or "" and why not. Never raises.

    ``fresh`` (the route, your own action): a refusal of this hand-in waits a whole :data:`HAND_IN_WAIT_S` again.
    ``claimed``: the caller already holds this conversation's claim (:func:`claim`); it is released here either way."""
    if not claimed and not claim(cid):
        return "", _BUSY
    try:
        return await _hand_in_again(app, project_root, catalog_root, cid, sid, fresh=fresh)
    finally:
        release(cid)


def hand_in_again_later(app: Any, project_root: Path, catalog_root: Path, cid: str, sid: str) -> None:
    """Start :func:`hand_in_again` for the route and return at once; the caller already holds the claim.

    The route used to await the whole hand-in, check included, inside the request and under the lock send-back shares.
    Now the answer comes at once and the listing says "checking" until the hand-in is out, or why it did not go."""

    async def run() -> None:
        submission, why = await hand_in_again(app, project_root, catalog_root, cid, sid, fresh=True, claimed=True)
        if not submission and why not in (_TAKEN, _BUSY):  # what the listing says in place of "checking"
            _note(cid, sid, state="gave up", why=f"it was not handed in again: {why}")
            log.warning("Thomas project %s: %s was not handed in again: %s", cid, sid, why)

    task = asyncio.create_task(run(), name=f"thomas-project:hand-in-again:{cid}")
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)


async def _hand_in_again(
    app: Any, project_root: Path, catalog_root: Path, cid: str, sid: str, *, fresh: bool
) -> tuple[str, str]:
    from thomas.server import precard, thomas_project
    from thomas.server.routes import evolve_agent_autopilot as ap

    try:
        submission, why = await precard.workers.off_the_loop(_settle_again, project_root, catalog_root, cid, sid)
        if submission is None:
            return "", why
        chat = await asyncio.to_thread(thomas_project.chat_to_follow, catalog_root, cid)
        record = await asyncio.to_thread(thomas_project.settled_record, catalog_root, cid) or {}
    except thomas_project.ChangeTooLarge as exc:  # the usual rule: it goes back to its team
        await ap.start_repair(app, project_root, catalog_root, cid, why=thomas_project.TOO_LARGE, detail=str(exc))
        return "", f"it breaks the repo's size rule, so it went back to its team: {exc}"
    except precard.ChangeFailedCheck as exc:  # Task 3h: the same rule, before the broad handler below
        await ap.start_repair(app, project_root, catalog_root, cid, why=ap.failed_check_reason(exc), detail=str(exc))
        return "", "the check before your card found something, so it went back to its team"
    except precard.ReviewUnavailable as exc:  # a hold, never a hand-in unchecked; the check it passed is kept
        return "", f"held: {exc}"
    except (TypeError, ValueError, KeyError, AttributeError, OSError, RuntimeError) as exc:
        log.exception("could not hand Thomas project %s in again", cid)
        return "", f"the hand-in failed: {exc}"
    _note(cid, sid, state="handed in", handed_in=submission.name, **({"since": _clock()} if fresh else {}))
    note = str(record.get("checked") or "")
    follow_it = ap._follow_verdict(app, project_root, catalog_root, cid, submission.name, chat, note)
    asyncio.create_task(follow_it, name=f"thomas-project:{submission.name}")
    log.info("Thomas project %s: %s handed in again as %s", cid, sid, submission.name)
    return submission.name, ""


def _give_up(cid: str, sid: str, why: str) -> str:
    from thomas.server import issue_ledger

    _note(cid, sid, state="gave up", why=why)
    log.warning("Thomas project %s: %s is not handed in again: %s", cid, sid, why)
    issue_ledger.record_issue(
        surface="thomas_project",
        kind="hand_in_again_gave_up",
        message=why,
        context={"conversation_id": cid, "submission": sid},
    )
    return ""


async def wait_then_hand_in(
    app: Any, project_root: Path, catalog_root: Path, cid: str, sid: str, files: list[str]
) -> str:
    """Wait until the running copy has no uncommitted work in *files*, then hand the same green in again, once.

    Polls every :data:`HAND_IN_POLL_S`, for at most :data:`HAND_IN_WAIT_S` from the first wait (a refusal of its own
    hand-in again waits within the same bound), then gives up and says why. A project something else took on since
    (a repair round, the route) is left to it. The new submission id, or "". Never raises.
    """
    from thomas.server import green_checkout, green_handoff, thomas_project

    with _waits_lock:
        prior = _WAITS.get(cid)
        if prior is not None and prior.sid == sid and prior.state == "waiting":
            return ""  # already waited on
    _note(cid, sid, state="waiting", files=list(files))
    try:
        while True:
            record = await asyncio.to_thread(thomas_project.settled_record, catalog_root, cid) or {}
            if str(record.get("submission") or "") != sid:
                return _drop(cid, sid)
            eid = str(record.get("execution_id") or "")
            if green_checkout.find_green(eid) is None:
                return _give_up(cid, sid, "its green copy is gone, so there is nothing to hand in again")
            dirty = await asyncio.to_thread(green_handoff.uncommitted_in_running_copy, eid, files)
            if dirty == []:
                submission, why = await hand_in_again(app, project_root, catalog_root, cid, sid)
                return submission or (_drop(cid, sid) if why in (_TAKEN, _BUSY) else _give_up(cid, sid, why))
            if dirty:
                _note(cid, sid, files=dirty)
            wait = hand_in_wait(cid)
            if wait is not None and _clock() - wait.since >= HAND_IN_WAIT_S:
                still = ", ".join(wait.files or files)
                return _give_up(
                    cid,
                    sid,
                    f"it waited {HAND_IN_WAIT_S / 3600:g} hours for the running copy's uncommitted work in {still} to "
                    f"be committed, and it still was not, so the change was not handed in again: commit or set that "
                    f"work aside, then POST {_again_url(cid)}",
                )
            await _sleep(HAND_IN_POLL_S)
    except asyncio.CancelledError:
        _drop(cid, sid)
        raise
    except (TypeError, ValueError, KeyError, AttributeError, OSError, RuntimeError) as exc:
        log.exception("waiting to hand Thomas project %s in again failed", cid)
        return _give_up(cid, sid, f"waiting for the running copy failed: {exc}")


def _drop(cid: str, sid: str) -> str:
    """Forget a wait that ended with nothing to say: the project is someone else's now."""
    with _waits_lock:
        wait = _WAITS.get(cid)
        if wait is not None and wait.sid == sid and wait.state == "waiting":
            del _WAITS[cid]
    return ""


__all__ = [
    "APPROVAL_WAIT_S",
    "DEV_MOVED",
    "HAND_IN_POLL_S",
    "HAND_IN_WAIT_S",
    "RUNNING_COPY_DIRTY",
    "VERDICTS",
    "HandInWait",
    "being_handed_in",
    "claim",
    "dev_moved",
    "follow",
    "hand_in_again",
    "hand_in_again_later",
    "hand_in_state",
    "hand_in_wait",
    "outbox_dir",
    "read_verdict",
    "refusal_text",
    "release",
    "uncommitted_files",
    "verdict_arrived",
    "wait_then_hand_in",
]
