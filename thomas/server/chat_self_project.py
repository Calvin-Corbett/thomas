"""Chat's hand-off of work on Thomas himself: a Thomas project with Build's team, not one worker.

You asked: "so when thomas works on himself make sure their is a task manegrr just for thomas project like he
does with every new build." Chat used to give a request to change Thomas to one chat worker in a green copy. In
self-fix round 5 (2026-09-24) all five such workers used 12 of 12 attempts and submitted nothing; four had made real
changes in their greens, and those were left for the 24h sweep.

Now ``send_task`` with ``workspace="project"`` starts a Thomas project (``thomas_project.start_thomas_project``):
Build's task manager and team in a green copy of Thomas's source, run with the chat's own settings (an Autopilot
request gets Autopilot's done check), landing only through your sign-in card, which shows in this chat. The chat's
task card links to the Build conversation and follows it to its end. If the project stops unfinished with real
changes, its green is kept and the card says where; the next request to change Thomas from this chat starts from
it. Every later project from the chat carries the earlier request and its outcome, and it is a new conversation:
Build refuses to continue a settled one (``project_is_thomas_source``).

If a project cannot start, or the server's own port is not known yet, the single worker still runs, and the reply
and the card say so ("Started as a single worker because ..."), so it never passes for a Thomas project.

Chat steers restart live runs; paused runs keep their card open for approval.
On restart, ``autopilot_restart`` resumes a run with a new card.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from thomas.core import task_bot_runtime
from thomas.core.file_access import PROJECT, clamp_file_access_level
from thomas.core.file_access import configured_file_access_level as _configured_level
from thomas.core.project_root import coordination_root
from thomas.core.task_titling import derive_task_title
from thomas.marketplace.orchestrator.bot_roster import pick_bot_for_specialist
from thomas.server import (
    autopilot_park,
    chat_delegation,
    green_checkout,
    green_handoff,
    self_change_status,
    thomas_project,
    thomas_project_quiet,
)
from thomas.server.app_keys import APP_LOCAL_PORT, APP_PRAXIS_STOP_CODE_RUN
from thomas.server.chat_delegation_emitter import _DelegationEmitter
from thomas.server.chat_delegation_session import _normalize_record, session_active_delegations
from thomas.server.thomas_project_successor import successor_greens, successor_id

log = logging.getLogger(__name__)

BACKEND = "thomas_project"
_ACTOR = "thomas-project"
_CARD_FIELDS = dict(intent="chat_task", scope=["coding"], visibility="background", backend_type=BACKEND, actor=_ACTOR)
_WORKING = "Build's task manager and team are working on it in a private copy of Thomas"
_HANDING_OVER = "Handing the change to your approval card"
RESTARTED_TEXT = (
    "Carrying on by himself: Thomas's server restarted while a Build run was working on this, and a new run has "
    "picked up where it stopped"
)
_AT_SIGN_IN = (
    "this change is already waiting for your decision on your approval card at the Windows sign-in. "
    "Decline it there, and nothing lands"
)
_FILE_ACCESS = ("read_only", "workspace", "project", "pc", "full")  # file_access levels 0-4, in Build's words
_EFFORTS = frozenset({"none", "low", "medium", "high", "xhigh", "max"})
_GUARDRAILS = frozenset({"open", "guarded", "fortress"})
_CARRY_CHARS = 1500
_POLL_S = 3.0
_HEARTBEAT_S = 60.0
_IDLE_GRACE_S = 120.0
_SWEEP_EVERY_S = 3600.0
_APPROVAL_WAIT_S = 24 * 3600.0
_OUTCOME_WORDS = {"awaiting_proof": "waiting for your approval", "cancelled": "stopped by you"}
_last_sweep: float | None = None
_sleep = asyncio.sleep


@dataclass
class _Card:
    app: Any
    eid: str
    root: Path
    cid: str
    execution_id: str
    project_root: Path
    catalog_root: Path
    emitter: _DelegationEmitter
    bot: Any
    note: str = ""  # said on every update: the unfinished changes this project resumed (Ruling AD)


# This process's followed cards, by chat task id: a steer can only reach a project something here follows.
_FOLLOWED: dict[str, _Card] = {}
# Kept greens a starting project is taking over right now, so two quick requests never share one.
_RESUMING: set[str] = set()


class _NoProject(Exception):  # noqa: N818 -- reads as what happened
    """A Thomas project did not start; the message is the reason the chat is told."""


def remember_chat_port(request: Any) -> None:
    """Learn the server's own port from a Chat request, the way a Build request already does."""
    from thomas.server.app_keys import local_port, remember_port

    try:
        remember_port(request.app, local_port(request))
    except (AttributeError, IndexError, OSError, TypeError, ValueError):
        log.debug("this chat request did not show the server's port", exc_info=True)


def build_settings(
    *, autonomy_level: Any, file_access: Any, model_id: Any, reasoning_effort: Any, guardrails: Any
) -> dict[str, Any]:
    """The chat's settings in Build's words. Chat sends no Build roles, so Build uses your saved team."""
    level = clamp_file_access_level(file_access if file_access is not None else _configured_level())
    settings: dict[str, Any] = {"autonomy_level": int(autonomy_level), "file_access": _FILE_ACCESS[level]}
    if model_id:
        settings.update(model=str(model_id), model_id=str(model_id))
    if str(reasoning_effort or "") in _EFFORTS:
        settings["reasoning_effort"] = str(reasoning_effort)
    if str(guardrails or "") in _GUARDRAILS:
        settings["guardrails"] = str(guardrails)
    return settings


async def start_background_delegation(app: Any, **kwargs: Any) -> dict[str, Any] | None:
    """``chat_delegation.start_background_delegation`` for Chat, with the same arguments, except that work on
    Thomas himself (``workspace="project"``) starts a Thomas project. This is the one place that decides."""
    access = kwargs.get("file_access")
    effective = clamp_file_access_level(access if access is not None else _configured_level())
    self_work = str(kwargs.get("workspace") or "").strip().lower() == "project"
    if not self_work or str(kwargs.get("surface") or "").strip().lower() == "canvas" or effective < PROJECT:
        # Below "This project" the worker path refuses with its own explanation, and nothing runs.
        return await chat_delegation.start_background_delegation(app, **kwargs)
    requested_at = time.time()
    root = coordination_root(kwargs.get("repo_root"), "project")
    try:
        started, profile = await _start_project(app, root, kwargs, requested_at=requested_at)
    except _NoProject as exc:
        return await _single_worker(app, str(exc), root, kwargs)
    try:
        return await _open_card(app, started, root, profile, kwargs)
    except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
        # M2: the project is running; only its card is missing. Say that, never "the hand-off failed".
        log.error("Thomas project %s started but its chat card did not open", started["conversation_id"], exc_info=True)
        note = (
            f"The Thomas project started (Build conversation {started['conversation_id']}), but its task card "
            f"could not open here ({type(exc).__name__}: {exc}). Open that conversation in Build to follow it."
        )
        await kwargs["emit_event"]({"type": "text", "text": f"\n\n{note}\n\n"})
        return {"execution_id": "", "state": "executing", "summary": note, "runtime_profile": profile}


async def _start_project(
    app: Any, root: Path, kwargs: dict[str, Any], *, requested_at: float | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Start the project and return it with its card's profile, or raise ``_NoProject`` with the reason.

    M1: whatever goes wrong -- the look-back, the settings, the start hook -- is logged with its traceback and
    becomes the fallback's reason; before, five named exception types did and anything else escaped unexplained.
    """
    port = app.get(APP_LOCAL_PORT)
    if not port:
        raise _NoProject("the server's own port was not known yet")
    sid, prompt = str(kwargs.get("session_id") or ""), str(kwargs.get("prompt") or "")
    resume: green_checkout.Green | None = None
    try:
        await _sweep_now_and_then(app)
        earlier, found = await asyncio.to_thread(_look_back, sid, root)
        resume = _claim(found, app, reserved=await asyncio.to_thread(successor_greens)) if found else None
        settings = build_settings(
            autonomy_level=kwargs.get("autonomy_level", 4),
            file_access=kwargs.get("file_access"),
            model_id=kwargs.get("model_id"),
            reasoning_effort=kwargs.get("reasoning_effort"),
            guardrails=kwargs.get("guardrails"),
        )
        started = await thomas_project.start_thomas_project(
            app,
            request=_carry(prompt, earlier, resume),
            settings=settings,
            port=int(port),
            green=resume,
            meta={"chat_session_id": sid, "requested_at": requested_at if requested_at is not None else time.time()},
        )
    except Exception as exc:  # any failure to start is the fallback's reason: logged here, raised as that reason
        log.exception("a Thomas project did not start for chat %s", sid)
        known = isinstance(exc, thomas_project.ThomasProjectError)
        raise _NoProject(str(exc) if known else f"{type(exc).__name__}: {exc}") from exc
    finally:
        if resume is not None:
            _RESUMING.discard(resume.execution_id)
    follows = str((earlier or {}).get("execution_id") or "")
    profile = {"request": prompt, "autonomy_level": settings["autonomy_level"], "follows_execution_id": follows}
    if resume is not None:  # Ruling AD: nothing rides onto your approval card unannounced
        kept = ((earlier or {}).get("runtime_profile") or {}).get("kept_green") or {}
        asked = str(((earlier or {}).get("runtime_profile") or {}).get("request") or (earlier or {}).get("summary"))
        profile["resumed_from"] = {"execution_id": follows, "request": asked, "files": list(kept.get("files") or [])}
    return started, profile


async def _sweep_now_and_then(app: Any) -> None:
    """I1: sweep greens when a project starts, at most hourly, off the loop, sparing any green in use.

    The single worker was the sweep's only caller; since Chat starts Thomas projects instead, greens that ended
    unsettled (and kept ones past ``green_checkout.KEPT_MAX_AGE_S``) were never removed.
    """
    global _last_sweep
    now = time.monotonic()
    if _last_sweep is not None and now - _last_sweep < _SWEEP_EVERY_S:
        return
    _last_sweep = now
    try:
        reserved = await asyncio.to_thread(successor_greens)
        removed = await asyncio.to_thread(_sweep_sparing, _greens_in_use(app, reserved=reserved))
    except (OSError, green_checkout.GreenUnavailable):
        log.warning("the green sweep did not finish", exc_info=True)
        return
    if removed:
        log.info("swept %d green(s): %s", len(removed), ", ".join(removed))


def _sweep_sparing(in_use: set[str]) -> list[str]:
    """Task 3b: a green kept for its verdict, or after one, is spared for 7 days from that verdict too."""
    return green_checkout.sweep(skip=in_use | green_handoff.held())


def _look_back(sid: str, root: Path) -> tuple[dict[str, Any] | None, green_checkout.Green | None]:
    """This chat's most recent Thomas project, and its kept green if one is still there to resume (Ruling AD)."""
    rows = [row for row in session_active_delegations(sid, repo_root=root) if row.get("backend_type") == BACKEND]
    earlier = rows[0] if rows else None
    kept = ((earlier or {}).get("runtime_profile") or {}).get("kept_green")
    resume = green_checkout.find_green(str(kept.get("execution_id") or "")) if isinstance(kept, dict) else None
    return earlier, resume


def _greens_in_use(app: Any, *, reserved: set[str] | None = None) -> set[str]:
    """Reserve followed cards, resuming starts, active Build runs, and successors between runs."""
    from thomas.server.routes.evolve_agent_run_state import APP_EVOLVE_AGENT_RUNS, slot_active

    work = (green_checkout.green_root() / "work").resolve()
    runs = app.get(APP_EVOLVE_AGENT_RUNS) or {}
    folders = [
        Path(str((slot.get("session") or {}).get("project_root") or "")) for slot in runs.values() if slot_active(slot)
    ]
    active = {folder.name for folder in folders if folder.name and folder.resolve().parent == work}
    reserved = successor_greens() if reserved is None else reserved
    return {card.execution_id for card in _FOLLOWED.values()} | set(_RESUMING) | active | reserved


def _claim(
    green: green_checkout.Green | None, app: Any, *, reserved: set[str] | None = None
) -> green_checkout.Green | None:
    """Claim a kept green if no project is already using it."""
    if green is None or green.execution_id in _greens_in_use(app, reserved=reserved):
        return None
    _RESUMING.add(green.execution_id)
    return green


def _carry(prompt: str, earlier: dict[str, Any] | None, resume: green_checkout.Green | None) -> str:
    if earlier is None:
        return prompt
    asked = str((earlier.get("runtime_profile") or {}).get("request") or earlier.get("summary") or "")
    state = str(earlier.get("state") or "unknown")
    if state == "awaiting_proof" and _card_hand_in_status(earlier) == "withdrawn":
        outcome = "withdrawn before your card; you were never asked"
    else:
        outcome = f"{_OUTCOME_WORDS.get(state, state)} -- {earlier.get('last_progress') or ''}".strip(" -")
    lines = [
        prompt,
        "",
        "This follows an earlier Thomas project from this chat.",
        f"Earlier request: {asked.strip()[:_CARRY_CHARS]}",
        f"Its outcome: {outcome[:_CARRY_CHARS]}",
    ]
    if resume is not None:
        lines.append("Its unfinished changes are already in this copy of Thomas; carry on from them.")
    return "\n".join(lines)


def _resumed_note(profile: dict[str, Any]) -> str:
    resumed = profile.get("resumed_from")
    if not isinstance(resumed, dict):
        return ""
    files = [str(f) for f in resumed.get("files") or []]
    shown = ", ".join(files[:5]) + (f", +{len(files) - 5} more" if len(files) > 5 else "")
    return f'It includes unfinished changes from the earlier request "{resumed.get("request")}": {shown}.'


def _say(card: _Card, text: str) -> str:
    return f"{text}. {card.note}" if card.note else text


def _new_card_record(sid: str, title: str, bot_id: str, profile: dict[str, Any], root: Path, opening: str) -> dict:
    row = task_bot_runtime.create_execution(
        session_id=sid, summary=title, bot_id=bot_id, runtime_profile=profile, repo_root=root, **_CARD_FIELDS
    )
    eid = str(row["execution_id"])
    for state in ("classified", "queued", "claimed", "executing"):
        summary = opening if state == "executing" else None
        row = task_bot_runtime.update_execution(
            eid, state=state, progress_summary=summary, actor=_ACTOR, repo_root=root
        )
    return row


async def _open_card(app: Any, started: dict[str, Any], root: Path, profile: dict[str, Any], kwargs: Any) -> dict:
    """The chat's task card for a started project: linked to its Build conversation, then followed to its end."""
    bot = pick_bot_for_specialist("coding")
    cid, green_id, work = (str(started[k]) for k in ("conversation_id", "execution_id", "project_root"))
    profile.update(build_conversation_id=cid, build_project_root=work, green_execution_id=green_id)
    sid, title, note = (
        str(kwargs.get("session_id") or ""),
        derive_task_title(profile["request"]),
        _resumed_note(profile),
    )
    opening = f"{_WORKING}. {note}" if note else _WORKING
    # M4: five index rewrites, 0.75-0.95 s on a board of 628 records, now off the event loop.
    row = await asyncio.to_thread(_new_card_record, sid, title, bot.id, profile, root, opening)
    eid = str(row["execution_id"])
    emitter = _DelegationEmitter(kwargs["emit_event"])
    card = _Card(app, eid, root, cid, green_id, Path(work), thomas_project._catalog_root(), emitter, bot, note)
    _FOLLOWED[eid] = card  # before anything else can await: a steer may arrive the moment the card shows
    asyncio.create_task(follow_card(card), name=f"thomas-project-card:{eid}")
    record = _normalize_record(row)
    await emitter.started(record, specialist_id="coding", bot=bot)
    return record


async def _no_stream(event: dict[str, Any]) -> None:
    """After a restart no chat stream is open to write to: the card's record is what the chat shows."""


def _follows(row: dict[str, Any]) -> str:
    """The Build conversation a card follows."""
    return str((row.get("runtime_profile") or {}).get("build_conversation_id") or "")


async def follow_after_restart(
    app: Any, cid: str, project_root: Path, catalog_root: Path, chat: str, *, text: str = ""
) -> str:
    """Task 3f: a restart stopped this project's run and ``autopilot_restart`` carried it on; its card follows again.

    The restart ended following; the startup sweep may close the card as interrupted. A new card in the same chat
    follows the resumed run, or an open card is followed again. Returns its id, or "" if no eligible card exists.
    ``text`` (from ``autopilot_hold_tick``: what a held change waits for) is said on the new card, or on the open one.
    """
    root = coordination_root(None, "project")
    rows = await asyncio.to_thread(session_active_delegations, chat, repo_root=root)
    mine = [r for r in rows if r.get("backend_type") == BACKEND and _follows(r) == cid]
    if not mine or any(card.cid == cid for card in _FOLLOWED.values()):
        return ""
    earlier, bot = mine[0], pick_bot_for_specialist("coding")
    profile = dict(earlier.get("runtime_profile") or {})
    if earlier.get("state") in task_bot_runtime.TERMINAL_STATES:
        if earlier.get("state") not in ("failed", "abandoned"):
            return ""
        profile["carried_on_from"] = str(earlier.get("execution_id") or "")
        title = str(earlier.get("summary") or derive_task_title(str(profile.get("request") or "")))
        earlier = await asyncio.to_thread(_new_card_record, chat, title, bot.id, profile, root, text or RESTARTED_TEXT)
    elif text:  # an open card: it says what the change waits for now
        await asyncio.to_thread(
            task_bot_runtime.update_execution, str(earlier["execution_id"]), actor=_ACTOR, repo_root=root,
            progress_summary=text,
        )  # fmt: skip
    eid, green = str(earlier["execution_id"]), str(profile.get("green_execution_id") or "")
    card = _Card(app, eid, root, cid, green, Path(project_root), catalog_root, _DelegationEmitter(_no_stream), bot)
    _FOLLOWED[eid] = card
    asyncio.create_task(follow_card(card), name=f"thomas-project-card:{eid}")
    return eid


async def _single_worker(app: Any, reason: str, root: Path, kwargs: dict[str, Any]) -> dict[str, Any] | None:
    note = f"Started as a single worker because {reason}. It is not a Thomas project: no task manager and no team."
    log.warning("chat self-change in %s: %s", kwargs.get("session_id"), note)
    record = await chat_delegation.start_background_delegation(app, **kwargs)
    eid = str((record or {}).get("execution_id") or "")
    current = task_bot_runtime.get_execution(eid, root) if eid else None
    if current and current.get("state") not in task_bot_runtime.TERMINAL_STATES:
        # The worker's task exists but has not taken its first step yet, so nothing races this write.
        profile = {**(current.get("runtime_profile") or {}), "single_worker_because": reason}
        task_bot_runtime.update_execution(
            eid, runtime_profile=profile, progress_summary=note, actor=_ACTOR, repo_root=root
        )
    await kwargs["emit_event"]({"type": "text", "text": f"\n\n{note}\n\n"})
    return record


def _card_hand_in_status(row: dict[str, Any]) -> str:
    profile = row.get("runtime_profile") or {}
    cid = str(profile.get("build_conversation_id") or "") if isinstance(profile, dict) else ""
    record = thomas_project.settled_record(thomas_project._catalog_root(), cid) if cid else None
    sid = str((record or {}).get("submission") or "")
    return str((self_change_status.read_hand_in_state(sid) or {}).get("status") or "") if sid else ""


def steer(eid: str, text: str, root: Any) -> dict[str, Any]:
    """Every steer from Chat -- the ``update_task`` tool and the card's steer route -- arrives here through
    ``chat_delegation.apply_task_update``. A worker's card queues it for the worker, as before. A Thomas project's
    goes to its Build run (fix round 1, I2): the chat says it was sent only once it was, and otherwise says why."""
    row = task_bot_runtime.get_execution(eid, root) or {}
    if row.get("backend_type") != BACKEND:
        task_bot_runtime.steer_execution(eid, text, actor="user", repo_root=root)
        return {"ok": True, "execution_id": eid, "action": "steer"}
    if row.get("state") == "awaiting_proof":
        status = _card_hand_in_status(row)
        why = (
            "this hand-in was withdrawn before your card; you were never asked"
            if status == "withdrawn"
            else _AT_SIGN_IN
        )
        return {"ok": False, "execution_id": eid, "error": f"Not sent: {why}"}
    card = _FOLLOWED.get(eid)
    if card is None:
        why = "this Thomas project is not followed here any more (Thomas restarted after it began)"
        return {"ok": False, "execution_id": eid, "error": f"Not sent: {why}. Open its Build conversation to steer it."}
    sent, said = _deliver(card, text)
    return {"ok": sent, "execution_id": eid, "action": "steer", ("delivery" if sent else "error"): said}


def stop(eid: str, root: Any) -> dict[str, Any]:
    """Every Stop from Chat -- the card's Stop and ``update_task(cancel=True)`` -- arrives here through
    ``chat_delegation.apply_task_update``. A card waiting for your approval is not stopped here, because that
    decision is yours at the sign-in (round 2, N4: it said "cancelled" and kept waiting)."""
    row = task_bot_runtime.get_execution(eid, root) or {}
    if row.get("backend_type") == BACKEND and row.get("state") == "awaiting_proof":
        status = _card_hand_in_status(row)
        why = (
            "this hand-in was withdrawn before your card; you were never asked"
            if status == "withdrawn"
            else _AT_SIGN_IN
        )
        return {"ok": False, "execution_id": eid, "error": f"Not stopped: {why}"}
    task_bot_runtime.request_cancel(eid, actor="user", repo_root=root)
    return {"ok": True, "execution_id": eid, "action": "cancel"}


def _deliver(card: _Card, text: str) -> tuple[bool, str]:
    from thomas.server.routes.evolve_agent_autopilot import interrupt_for_steer
    from thomas.server.routes.evolve_agent_run_state import APP_EVOLVE_AGENT_RUNS, slot_active, slot_running

    slot = (card.app.get(APP_EVOLVE_AGENT_RUNS) or {}).get(card.cid)
    if slot_running(slot):  # Build's own steer: stop the run, and the next one starts with your change
        thomas_project.hold_steer(card.cid, text)
        interrupt_for_steer(card.app, card.cid)
        return True, "Sent: the running Build run is stopping, and the next one starts with your change first."
    if slot_active(slot):
        thomas_project.hold_steer(card.cid, text)
        return True, "Queued: the run is saving its result, and the next one starts with your change first."
    phase, detail = _phase(card)
    if detail == thomas_project_quiet.CHECKING:  # hand_in_hold: being checked, so nothing has gone to a card yet
        thomas_project.hold_steer(card.cid, text)
        return True, "Queued: the change being checked has not been handed in; the next Build run starts with yours."
    if phase == "paused":  # a usage limit (autopilot_park) or a held check (hand_in_hold): either way it ends now
        thomas_project.hold_steer(card.cid, text)
        return True, "Queued: your change ends the pause, and the next Build run starts with it first."
    if phase in ("waiting", "resumed") and detail != _HANDING_OVER:
        thomas_project.hold_steer(card.cid, text)
        return True, "Queued: the next Build run starts with your change first."
    if (
        phase != "ended"
        and _card_hand_in_status({"runtime_profile": {"build_conversation_id": card.cid}}) == "withdrawn"
    ):
        why = "its hand-in was withdrawn before your card; you were never asked"
    else:
        why = "it has been handed to your approval card" if phase != "ended" else f"it has stopped ({detail})"
    return False, f"Not sent: {why}. Ask for a new change instead."


def _run_active(app: Any, cid: str) -> bool:
    from thomas.server.routes.evolve_agent_run_state import APP_EVOLVE_AGENT_RUNS, slot_active

    registry = app.get(APP_EVOLVE_AGENT_RUNS)
    return isinstance(registry, dict) and slot_active(registry.get(cid))


def _phase(card: _Card) -> tuple[str, str]:
    phase = thomas_project.project_phase(card.project_root, card.catalog_root, card.cid)
    if phase[0] == "paused":  # has the run after the pause started? A read caught mid-write keeps "paused"
        return autopilot_park.card_words(card.project_root, card.catalog_root, card.cid) or phase
    return phase


def _run_progress(card: _Card) -> str:
    """Read only this conversation's recorded Build events, never infer success from activity.

    The registry owns the transcript path. Do not derive a path from a chat id or
    fall back to another run's slot: simultaneous Build runs must not mix cards.
    """
    from thomas.server.routes.evolve_agent_run_state import APP_EVOLVE_AGENT_RUNS

    registry = card.app.get(APP_EVOLVE_AGENT_RUNS)
    slot = registry.get(card.cid) if isinstance(registry, dict) else None
    session = slot.get("session") if isinstance(slot, dict) else None
    path = session.get("transcript") if isinstance(session, dict) else None
    if not path or str(session.get("conversation_id") or "") != card.cid:
        return ""
    try:
        # A bounded tail avoids loading long-running transcripts on every poll.
        with Path(path).open("rb") as stream:
            stream.seek(0, 2)
            end = stream.tell()
            stream.seek(max(0, end - 128_000))
            tail = stream.read().decode("utf-8", errors="replace")
    except (OSError, ValueError, TypeError):
        return ""
    lines = tail.splitlines()
    if end > 128_000:
        lines = lines[1:]  # the first line may start halfway through an event
    if tail and not tail.endswith("\n"):
        lines = lines[:-1]  # a writer may still be appending the last event
    # Ignore unfinished writes, deltas, tool payloads, private reasoning and
    # final claims. A progress line is an observation, not an approval receipt.
    for line in reversed(lines):
        try:
            event = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(event, dict) or event.get("fc") not in {"say", "insight", "planning", "meta"}:
            continue
        if event.get("delta") or event.get("is_thinking") or event.get("terminal"):
            continue
        text = " ".join(str(event.get("text") or "").split()).strip()
        if text:
            return text[:400].rstrip() + ("…" if len(text) > 400 else "")
    return ""


async def _follow_successor(card: _Card) -> bool:
    cid = await asyncio.to_thread(successor_id, card.project_root, card.catalog_root, card.cid)
    if not cid or cid == card.cid:
        return False
    previous = card.cid
    row = await asyncio.to_thread(task_bot_runtime.get_execution, card.eid, card.root) or {}
    profile = {**(row.get("runtime_profile") or {}), "build_conversation_id": cid}
    text = f"A new Thomas project carries the unfinished change and review findings on from {previous}."
    updated = await asyncio.to_thread(_update, card, state="running", runtime_profile=profile, progress_summary=text)
    card.cid = cid  # keep this card (and its green reservation) through the next project's checks and rounds
    _FOLLOWED[card.eid] = card
    await card.emitter.progress(_normalize_record(updated), specialist_id="coding", bot=card.bot, text=text)
    return True


def _check(card: _Card) -> tuple[bool, tuple[str, str]]:
    return task_bot_runtime.is_cancel_requested(card.eid, repo_root=card.root), _phase(card)


def _update(card: _Card, **fields: Any) -> dict[str, Any]:
    return task_bot_runtime.update_execution(card.eid, actor=_ACTOR, repo_root=card.root, **fields)


async def follow_card(card: _Card) -> None:
    """Follow the project's handoffs until it settles or stops, without raising into Chat."""
    loop = asyncio.get_running_loop()
    idle_since: float | None = None
    shown, beat = _WORKING, loop.time()
    _FOLLOWED[card.eid] = card
    try:
        while True:
            await _sleep(_POLL_S)
            cancelled, (phase, detail) = await asyncio.to_thread(_check, card)
            if cancelled:  # M5: no next Autopilot round either, between rounds as much as mid-run
                await asyncio.to_thread(thomas_project.request_stop, card.project_root, card.cid)
                await asyncio.to_thread(autopilot_park.clear, card.project_root, card.catalog_root, card.cid)
                await _stop_run(card)
                return await _end(card, "you stopped it", cancelled=True)
            if await _follow_successor(card):
                idle_since = None
                shown = ""
                continue
            active = _run_active(card.app, card.cid)
            if phase == "settled":
                if await _settled(card):  # Task 3b: back with its team for a repair round, followed again
                    idle_since = None
                    continue
                return
            if phase == "ended" and not active:
                return await _end(card, detail)
            # A pause for your usage limit, a held check and a check that is running are not quiet: each goes on.
            if active or phase == "paused" or detail == thomas_project_quiet.CHECKING:
                idle_since = None
            elif idle_since is None:
                idle_since = loop.time()
            elif loop.time() - idle_since > _IDLE_GRACE_S:
                return await _end(card, f"it went quiet for {int(_IDLE_GRACE_S)} s after: {detail or 'its start'}")
            progress = await asyncio.to_thread(_run_progress, card) if active else ""
            text = detail if detail and (not active or phase == "resumed") else _WORKING
            text = f"Build update: {progress}" if progress else text  # a recorded line wins while it runs
            if text != shown or loop.time() - beat >= _HEARTBEAT_S:  # M4: no index rewrite when nothing changed
                said = _say(card, text) if text != shown else None
                row = await asyncio.to_thread(_update, card, heartbeat=True, progress_summary=said)
                beat = loop.time()
                if said:
                    shown = text
                    await card.emitter.progress(_normalize_record(row), specialist_id="coding", bot=card.bot, text=said)
    except asyncio.CancelledError:
        raise
    except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError):
        log.exception("the chat card for Thomas project %s stopped following it", card.cid)
    finally:
        _FOLLOWED.pop(card.eid, None)


async def _stop_run(card: _Card) -> None:
    from thomas.server.routes.evolve_agent_run_state import APP_EVOLVE_AGENT_RUNS

    slot = (card.app.get(APP_EVOLVE_AGENT_RUNS) or {}).get(card.cid) or {}
    run_id = str((slot.get("session") or {}).get("run_id") or "")
    stop = card.app.get(APP_PRAXIS_STOP_CODE_RUN)
    if run_id and stop is not None:
        await stop(run_id)


async def _settled(card: _Card) -> bool:
    """Keep a submitted change open through its verdict and any successor after the last repair round."""
    record = await asyncio.to_thread(thomas_project.settled_record, card.catalog_root, card.cid) or {}
    submission, who = str(record.get("submission") or ""), {"specialist_id": "coding", "bot": card.bot}
    if not submission:
        if await _follow_successor(card):
            return True
        text = str(record.get("summary") or "")
        if not text.endswith("already passes; no code change or sign-in card."):
            text = "Finished without changing any of Thomas's files, so there was nothing to approve."
        row = await asyncio.to_thread(
            task_bot_runtime.complete_execution, card.eid, actor=_ACTOR, summary=text, verified_success=True,
            repo_root=card.root,
        )  # fmt: skip
        await card.emitter.completed(_normalize_record(row), text=text, **who)
        return False
    verdict = await asyncio.to_thread(self_change_status.read_hand_in_state, submission)
    if verdict is None:
        text = _say(card, f"Submitted for your approval ({record.get('summary')}). Approve or decline it at the Windows "
                          "sign-in; its card shows in this chat")  # fmt: skip
        row = await asyncio.to_thread(_update, card, state="awaiting_proof", progress_summary=text)
        await card.emitter.progress(_normalize_record(row), text=text, **who)
        verdict = await _await_verdict(card, submission)
        if verdict is None:
            verdict = await asyncio.to_thread(self_change_status.read_hand_in_state, submission)
    status, detail = str((verdict or {}).get("status") or ""), self_change_status.refusal_text(verdict)
    arrived = self_change_status.verdict_arrived
    kept = (
        await asyncio.to_thread(arrived, verdict, execution_id=card.execution_id, sid=submission)
        if verdict and status != "withdrawn"
        else ""
    )
    if status == "landed":
        text = f"Landed: your approval put it into the running Thomas ({detail or submission})."
        row = await asyncio.to_thread(
            task_bot_runtime.complete_execution, card.eid, actor=_ACTOR, summary=text, verified_success=True,
            repo_root=card.root,
        )  # fmt: skip
        await card.emitter.completed(_normalize_record(row), text=text, **who)
        return False
    if await _follow_successor(card):
        return True
    rounds = thomas_project.repairs_done(record)
    if self_change_status.dev_moved(verdict):
        return await _repairing(card, submission, detail, rounds + 1)
    if status == "withdrawn":
        text = _say(card, f"Withdrawn before your card: you were never asked about {submission}")
        row = await asyncio.to_thread(task_bot_runtime.mark_abandoned, card.eid, actor=_ACTOR, summary=text,
                                      repo_root=card.root)  # fmt: skip
    elif verdict is None:
        text = "Thomas stopped waiting for your answer after 24 hours; its approval card may still be waiting."
        row = await asyncio.to_thread(task_bot_runtime.mark_abandoned, card.eid, actor=_ACTOR, summary=text,
                                      repo_root=card.root)  # fmt: skip
    elif status == "declined":  # your decision, not a failure
        said = (f"{self_change_status.VERDICTS['declined']}.", kept, "Nothing is retried.")
        text = " ".join(part for part in said if part)
        row = await asyncio.to_thread(
            task_bot_runtime.cancel_execution, card.eid, actor="user", summary=text, repo_root=card.root
        )
        await card.emitter.progress(_normalize_record(row), text=text, **who)
        return False
    else:  # the promoter's words, whole: never a bare "failed"
        sentence = self_change_status.VERDICTS.get(status, self_change_status.VERDICTS["error"])
        moved = self_change_status.dev_moved(verdict)
        again = ", and dev moved on under it again; no successor link appeared" if moved else ""
        text = " ".join(part for part in (f"{sentence} ({detail or status}){again}.", kept) if part)
        row = await asyncio.to_thread(
            task_bot_runtime.fail_execution, card.eid, actor=_ACTOR, summary=text, blocker=f"self_change_{status}",
            repo_root=card.root,
        )  # fmt: skip
    await card.emitter.failed(_normalize_record(row), text=text, **who)
    return False


async def _await_successor(card: _Card) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _IDLE_GRACE_S
    while loop.time() < deadline:
        if await _follow_successor(card):
            return True
        await _sleep(_POLL_S)
    return await _follow_successor(card)


async def _repairing(card: _Card, submission: str, detail: str, number: int) -> bool:
    """Dev moved on under the change, and Autopilot sends it back to its team (``evolve_agent_autopilot.
    start_repair``): the card says so, goes back to working, and follows the project again once it has."""
    text = _say(card, f"Dev moved on after this change was made, so the promoter refused it ({detail}). Build's team "
                      f"is merging dev into its copy and will hand it in again: repair round {number}")  # fmt: skip
    row = await asyncio.to_thread(_back_to_work, card, text)
    await card.emitter.progress(_normalize_record(row), specialist_id="coding", bot=card.bot, text=text)
    if await _await_repair(card, submission):
        return True
    await _end(card, f"dev moved on under the change, and its repair round did not start in {int(_IDLE_GRACE_S)} s")
    return False


def _back_to_work(card: _Card, text: str) -> dict[str, Any]:
    """From waiting for your approval back to working: through ``blocked``, the only way the task states allow."""
    _update(card, state="blocked", progress_summary=text)
    return _update(card, state="executing", progress_summary=text)


async def _await_repair(card: _Card, submission: str) -> bool:
    """Until the repair round takes the project back from the approval card: its settled copy is gone, or newer."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _IDLE_GRACE_S
    while loop.time() < deadline:
        record = await asyncio.to_thread(thomas_project.settled_record, card.catalog_root, card.cid)
        if str((record or {}).get("submission") or "") != submission:
            return True
        await _sleep(_POLL_S)
    return False


async def _await_verdict(card: _Card, submission: str) -> dict[str, Any] | None:
    loop = asyncio.get_running_loop()
    deadline, beat = loop.time() + _APPROVAL_WAIT_S, loop.time()
    while loop.time() < deadline:
        verdict = await asyncio.to_thread(self_change_status.read_hand_in_state, submission)
        if verdict is not None:
            return verdict
        if loop.time() - beat >= _HEARTBEAT_S:
            await asyncio.to_thread(_update, card, heartbeat=True)
            beat = loop.time()
        await _sleep(_POLL_S)
    return None


async def _end(card: _Card, reason: str, *, cancelled: bool = False) -> None:
    """Ruling V: a project that stops unfinished keeps a green with real changes, and the card says where."""
    _FOLLOWED.pop(card.eid, None)
    unsent = thomas_project.held_steers(card.cid)  # round 2, N1: a steer no run took is said, never lost quietly
    thomas_project.drop_steers(card.cid, len(unsent))
    kept = await asyncio.to_thread(thomas_project.keep_unfinished, card.execution_id, reason)
    if kept:
        files = list(kept["files"])
        shown = ", ".join(files[:5]) + (f", +{len(files) - 5} more" if len(files) > 5 else "")
        text = (
            f"The Thomas project stopped before it finished: {reason}. Its changes to {len(files)} file(s) ({shown}) "
            f"are kept in {kept['work']}; the next request to change Thomas in this chat carries on from them."
        )
        current = await asyncio.to_thread(task_bot_runtime.get_execution, card.eid, card.root) or {}
        profile = {**(current.get("runtime_profile") or {}), "kept_green": kept}
        await asyncio.to_thread(_update, card, runtime_profile=profile)
    else:
        text = f"The Thomas project stopped before it finished: {reason}. No changed files were found in its copy."
    if unsent:
        text += f" Your steering was not sent to any run: {'; '.join(unsent)}."
    who = {"specialist_id": "coding", "bot": card.bot, "text": text}
    if cancelled:
        row = await asyncio.to_thread(
            task_bot_runtime.cancel_execution, card.eid, actor="user", summary=text, repo_root=card.root
        )
        await card.emitter.progress(_normalize_record(row), **who)
    else:
        row = await asyncio.to_thread(
            task_bot_runtime.fail_execution, card.eid, actor=_ACTOR, summary=text,
            blocker="thomas_project_unfinished", repo_root=card.root,
        )  # fmt: skip
        await card.emitter.failed(_normalize_record(row), **who)


__all__ = [
    "BACKEND",
    "build_settings",
    "follow_after_restart",
    "follow_card",
    "remember_chat_port",
    "start_background_delegation",
    "steer",
    "stop",
]
