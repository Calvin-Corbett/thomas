"""Start and list Thomas projects at ``/api/self/projects`` without Chat.

``POST {request, settings, chat_session_id?}`` validates Build's dials and calls
``thomas_project.start_thomas_project``; ``GET`` uses the shared listing cache.
``POST {id}/send-back {findings}`` repairs an unlanded hand-in after it leaves the
inbox, or starts its successor when repair rounds are spent.
``POST {id}/stop`` stamps the conversation, clears its park and asks Build to stop.
``POST {id}/hand-in-again`` retries eligible refused hand-ins in the background,
answering 202 and blocking duplicates while checks run.
All routes use the supplied loopback guard; no CORS headers are sent.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.core.acceptance_launch_notice import long_requirements, long_requirements_notice
from thomas.forge.anvil import forge_code_projects, forge_code_store
from thomas.forge.anvil.forge_code_settings import ForgeCodeSettings, ForgeCodeSettingsError
from thomas.server import (
    autopilot_park,
    autopilot_restart,
    green_checkout,
    green_handoff,
    hand_in_hold_store,
    self_change_status,
    thomas_project,
)
from thomas.server.app_keys import APP_PRAXIS_START_CODE_RUN, APP_PRAXIS_STOP_CODE_RUN, local_port, remember_port
from thomas.server.dial_elevation import cap_payload
from thomas.server.routes import self_project_unreadable
from thomas.server.routes.evolve_agent_autopilot import start_repair
from thomas.server.routes.evolve_agent_http_support import code_execution_settings_response
from thomas.server.routes.evolve_agent_run_state import APP_EVOLVE_AGENT_RUNS, slot_active
from thomas.server.routes.self_project_listing_cache import read_listing as read_project_listing
from thomas.server.routes.self_project_listing_cache import read_project_records, read_record, read_registry
from thomas.server.routes.self_project_timing import add_timings

log = logging.getLogger(__name__)

PATH = "/api/self/projects"
SEND_BACK_PATH = PATH + "/{conversation_id}/send-back"
HAND_IN_AGAIN_PATH = PATH + "/{conversation_id}/hand-in-again"
STOP_PATH = PATH + "/{conversation_id}/stop"
# Build's dials only; the start owns the conversation, folder, attachments and request id.
SETTINGS_KEYS = frozenset(
    {
        "engine",
        "model",
        "model_id",
        "reasoning_effort",
        "autonomy_level",
        "file_access",
        "memory",
        "guardrails",
        "token_economy",
        "build_roles",
    }
)
_REQUEST_MAX_CHARS = 50_000
_FINDINGS_MAX_CHARS = 20_000
_CHAT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_SUBMISSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,160}$")  # green_handoff: self-<execution id>[-<n>]
_RECENT_SHOWN = 20
_CONVERSATIONS = Path(".thomas") / "evolve" / "agent" / "conversations"


class GreensUnreadable(OSError):
    """The green listing was incomplete; keep the conversations that were readable."""

    def __init__(self, found: list[tuple[Path, dict[str, Any]]], unread: list[str]) -> None:
        super().__init__("; ".join(unread))
        self.found = found
        self.unread = unread


def _unreadable(path: Path, exc: BaseException, *, folder: bool = False) -> str:
    strerror = getattr(exc, "strerror", None)
    text = f"{path} could not be read ({type(exc).__name__}: {strerror or str(exc)})"
    return self_project_unreadable.unread(path, exc, text, folder=folder)


def _refuse(status: int, reason: str) -> web.Response:
    return web.json_response({"ok": False, "error": reason}, status=status)


STALL_RETRIES = 2  # a start that stood still is begun again this many times before it is reported


async def _start_waiting_out_stalls(
    app: Any, ask: str, settings: dict[str, Any], port: int, meta: dict[str, Any]
) -> Any:
    """Start a Thomas project; a preparation that stood still is not a failure, so begin it again before reporting one.

    The stalled attempt cleaned up after itself (its green copy and registry row are gone), so a second start is
    a fresh one. Any other refusal is raised at once."""
    for attempt in range(STALL_RETRIES + 1):
        try:
            return await thomas_project.start_thomas_project(app, request=ask, settings=settings, port=port, meta=meta)
        except thomas_project.ThomasProjectError as exc:
            if "preparation stalled" not in str(exc) or attempt == STALL_RETRIES:
                raise
            log.info("Thomas project start stalled (attempt %d); starting it again", attempt + 1)
    raise AssertionError("unreachable")  # pragma: no cover -- the loop returns or raises


def _checked(body: Any) -> web.Response | tuple[str, dict[str, Any], str]:
    """The request, Build settings and chat a start asks for, or the refusal that says what is wrong with them."""
    if not isinstance(body, dict):
        return _refuse(400, "the body must be a JSON object: {request, settings, chat_session_id?}")
    ask = body.get("request")
    if not isinstance(ask, str) or not ask.strip():
        return _refuse(400, "request is empty: say what Thomas should change about himself")
    if len(ask) > _REQUEST_MAX_CHARS:
        return _refuse(400, f"request is longer than {_REQUEST_MAX_CHARS} characters")
    settings = body.get("settings")
    if not isinstance(settings, dict):
        return _refuse(400, "settings must be an object of Build's settings: model, model_id, reasoning_effort, ...")
    unknown = sorted(str(key) for key in settings if key not in SETTINGS_KEYS)
    if unknown:
        return _refuse(400, f"settings Build does not take here: {', '.join(unknown)}")
    chat = body.get("chat_session_id") or ""
    if chat and not (isinstance(chat, str) and _CHAT_ID.fullmatch(chat)):
        return _refuse(400, "chat_session_id is not a chat id")
    try:  # Build's send route: the settings it will actually honour, then whether they may edit at all
        effective = ForgeCodeSettings.from_payload(cap_payload(dict(settings)))
    except ForgeCodeSettingsError as exc:
        return _refuse(400, str(exc))
    blocked = code_execution_settings_response(effective)
    return blocked if blocked is not None else (ask, dict(settings), chat)


def _project(conversation: dict[str, Any]) -> dict[str, Any]:
    project = conversation.get("thomas_project")
    return project if isinstance(project, dict) else {}


def _conversations(
    folder: Path, *, strict: bool = False, unread: list[str] | None = None, warnings: list[str] | None = None
) -> list[dict[str, Any]]:
    return read_project_records(folder, strict=strict, warnings=warnings, failures=unread)


def _in_greens(warnings=None) -> list[tuple[Path, dict[str, Any]]]:
    work_root = green_checkout.green_root() / "work"
    try:
        works = sorted(work_root.iterdir())
    except FileNotFoundError:
        return []
    except OSError as exc:
        text = f"{work_root} could not be read ({type(exc).__name__}: {exc.strerror or exc})"
        raise GreensUnreadable([], [text]) from exc
    found: list[tuple[Path, dict[str, Any]]] = []
    unread: list[str] = []
    for work in works:
        folder = work / _CONVERSATIONS
        try:
            if not work.is_dir():
                continue
            found.extend((work, c) for c in _conversations(folder, strict=True, unread=unread, warnings=warnings))
        except OSError as exc:
            message = f"Skipped Thomas project {work.name}: its conversations could not be read ({exc})."
            unread.append(_unreadable(folder, exc, folder=True))
            log.warning(message)
            if warnings is not None and message not in warnings:
                warnings.append(message)
    if unread:
        raise GreensUnreadable(found, unread)
    return found


def _changed(conversation: dict[str, Any], in_greens: dict[str, list[str]]) -> list[str]:
    """What the green's patch changes, read without staging; once the green is gone, what its runs changed."""
    files = in_greens.get(str(_project(conversation).get("execution_id") or ""))
    if files:
        return files
    turns = [t for t in conversation.get("turns") or [] if isinstance(t, dict) and t.get("role") == "agent"]
    return list(dict.fromkeys(str(name) for turn in turns for name in turn.get("changed_files") or []))


def _verdict(sid: str) -> dict[str, Any] | None:
    verdict = self_change_status.read_hand_in_state(sid) if _SUBMISSION_ID.fullmatch(sid) else None
    if verdict is None:
        return None
    status = str(verdict.get("status") or "error")
    return {"submission": sid, "status": status, "detail": self_change_status.refusal_text(verdict)}


def _earlier_verdict(project: dict[str, Any]) -> dict[str, Any] | None:
    """What sent the project back for its latest repair round: the promoter's verdict, or, for a change sent back
    after a check (Task 3d), that it was sent back and the first line of why. A withdrawn hand-in has no verdict."""
    if project.get("handed_in_after"):  # handed in again once the running copy's work was committed (Task 3g)
        return _verdict(str(project["handed_in_after"]))
    rounds = [done for done in project.get("repairs") or [] if isinstance(done, dict)]
    if not rounds:
        return None
    last, sid = rounds[-1], str(rounds[-1].get("sid") or "")
    if last.get("why") != thomas_project.SENT_BACK:
        return _verdict(sid)
    why = next((line.strip() for line in str(last.get("detail") or "").splitlines() if line.strip()), "")
    return {"submission": sid, "status": "sent_back", "detail": why}


def _row(conversation: dict[str, Any], state: str, detail: str, verdict: Any, files: dict[str, list[str]]) -> dict:
    project = _project(conversation)
    return {
        "conversation_id": str(conversation.get("id") or ""),
        "execution_id": str(project.get("execution_id") or ""),
        **({"queue_id": str(project["queue_id"])} if project.get("queue_id") else {}),
        "title": str(conversation.get("title") or ""),
        "chat_session_id": str(project.get("chat_session_id") or ""),
        "state": state,
        "detail": detail,
        "submission": str(project.get("submission") or (project.get("retirement") or {}).get("submission") or ""),
        "checked": str(project.get("checked") or ""),  # what the check before the card found (Task 3h)
        "last_verdict": verdict,
        "changed_files": _changed(conversation, files),
        "updated_at": str(project.get("settled_at") or conversation.get("updated_at") or ""),
    }


def _handed_in(
    conversation: dict[str, Any], files: dict[str, list[str]], event: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Show a catalog copy's settled hand-in or its recorded repair ending."""
    project = _project(conversation)
    retirement = project.get("retirement") or {}
    if retirement.get("outcome") == "reported":
        return _row(conversation, "reported", str(retirement.get("reason") or ""), None, files)
    if not project.get("settled_at") and not retirement:
        if project.get("hold_settle") and event and event.get("state") == "reported":
            return _row(conversation, "reported", str(event.get("reason") or ""), None, files)
        return _row(conversation, "handing in", "being handed to your approval card", None, files)
    sid = str(project.get("submission") or retirement.get("submission") or "")
    if not sid:
        return _row(conversation, "no changes", "it finished without changing Thomas's files", None, files)
    verdict = _verdict(sid)
    if verdict is None:
        waiting = f"{sid} waits for your answer at the Windows sign-in"
        return _row(conversation, "awaiting verdict", waiting, _earlier_verdict(project), files)
    if verdict["status"] == "withdrawn":
        return _row(conversation, "withdrawn", verdict["detail"], _earlier_verdict(project), files)
    cid = str(conversation.get("id") or "")
    waiting = self_change_status.hand_in_state(cid, sid, verdict["detail"]) if verdict["status"] == "refused" else None
    if waiting is not None:  # Task 3g: refused only for the running copy's uncommitted work
        return _row(conversation, *waiting, verdict, files)
    words = self_change_status.VERDICTS.get(verdict["status"], self_change_status.VERDICTS["error"])
    return _row(conversation, verdict["status"], words, verdict, files)


def _in_green(
    work: Path,
    catalog: Path,
    conversation: dict[str, Any],
    files: dict,
    running: bool,
    *,
    metadata: dict[str, Any] | None = None,
    hold_rows: list[dict[str, Any]] | None = None,
    catalog_conversation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A project its team still has: running, on a repair round, paused for a usage limit, or stopped."""
    cid = str(conversation.get("id") or "")
    project = _project(conversation)
    if not running and thomas_project.stop_requested(conversation):
        return _row(conversation, "stopped", autopilot_restart.YOU_STOPPED, _earlier_verdict(project), files)
    kwargs = {}
    if "conversation" in inspect.signature(thomas_project.project_phase).parameters:
        kwargs = dict(
            conversation=conversation, metadata=metadata, hold_rows=hold_rows, catalog_conversation=catalog_conversation
        )
    phase, why = (
        ("waiting", "a Build run is going") if running else thomas_project.project_phase(work, catalog, cid, **kwargs)
    )
    earlier = _earlier_verdict(project)
    if phase in ("ended", "paused"):
        return _row(conversation, "stopped" if phase == "ended" else "paused", why, earlier, files)
    rounds = thomas_project.repairs_done(project)
    state = f"repair round {rounds}" if rounds else "running"
    return _row(conversation, state, why or "its first Build run is starting", earlier, files)


def list_projects(catalog: Path, running: frozenset[str] | set[str] = frozenset()) -> list[dict[str, Any]]:
    """Every Thomas project still in a green, newest first, then the most recent ones handed in. Read-only."""
    return read_projects(catalog, running)["projects"]


def read_projects(
    catalog: Path | None = None, running: frozenset[str] | set[str] | None = None, *, changed_files: bool = True
) -> dict[str, Any]:
    """List readable projects and say which green copies could not be read."""
    catalog = catalog if catalog is not None else thomas_project._catalog_root()
    warnings: list[str] = []
    knows_runs, running, whole = running is not None, running or frozenset(), True
    try:
        greens, unread = _in_greens(warnings), []
    except GreensUnreadable as exc:
        greens, unread, whole = exc.found, exc.unread, False
    # The copies a run is working in now: only those, and the ones worked in lately, are walked for their changes.
    # A caller with no registry of runs, or a list of copies that could not be read whole, says nothing about them.
    if knows_runs and whole:
        green_handoff.runs_are_in(
            Path(work).name for work, conversation in greens if str(conversation.get("id") or "") in running
        )
    files = green_handoff.sibling_changes("") if changed_files else {}
    in_greens = len(unread)
    try:
        handed = {
            str(c.get("id") or ""): c
            for c in _conversations(catalog / _CONVERSATIONS, strict=True, unread=unread, warnings=warnings)
        }
    except OSError as exc:
        handed = {}
        unread.append(f"{catalog}: {exc}")
    registry, live = read_registry(catalog, unread), []
    self_project_unreadable.not_greens(unread[in_greens:])
    hold_rows: list[dict[str, Any]] | None = None
    for work, conversation in greens:
        cid = str(conversation.get("id") or "")
        if cid in handed:  # the handed-in copy speaks for it until a repair round
            continue
        if cid not in running and not thomas_project.stop_requested(conversation) and hold_rows is None:
            hold_rows = hand_in_hold_store.rows(catalog)
        kwargs = {
            "metadata": registry.get(cid) or {},
            "hold_rows": hold_rows,
            "catalog_conversation": handed.get(cid),
        }
        live.append(_in_green(work, catalog, conversation, files, cid in running, **kwargs))
    live.sort(key=lambda row: row["updated_at"], reverse=True)
    recent = sorted(
        handed.values(),
        key=lambda c: str(_project(c).get("settled_at") or c.get("updated_at") or ""),
        reverse=True,
    )[:_RECENT_SHOWN]
    missing = {
        str(c.get("id") or "")
        for c in recent
        if _project(c).get("hold_settle") and not _project(c).get("settled_at") and not _project(c).get("retirement")
    }
    events: dict[str, dict[str, Any]] = {}
    if missing:
        from thomas.server.ratchet.ledger import Ledger

        for event in Ledger().events():
            cid = str(event.get("conversation_id") or "")
            if cid in missing:
                events[cid] = event
    unread, skipped = self_project_unreadable.settle(unread, immediate=True)
    live += self_project_unreadable.rows(skipped)
    rows = live + [_handed_in(c, files, events.get(str(c.get("id") or ""))) for c in recent]
    conversations = {str(c.get("id") or ""): c for _, c in greens} | handed
    timing = add_timings(rows, conversations, catalog, running=running)
    return {"ok": True, "projects": rows, "unreadable": unread, "skipped": skipped, "warnings": warnings, **timing}


def _running(app: Any) -> set[str]:
    runs = app.get(APP_EVOLVE_AGENT_RUNS) or {}
    return {str(cid) for cid, slot in runs.items() if slot_active(slot)}


def running_projects(app: Any) -> set[str]:
    return _running(app)


def _findings(body: Any) -> web.Response | str:
    """The findings a send-back carries, or the refusal that says what is wrong with them."""
    if not isinstance(body, dict):
        return _refuse(400, "the body must be a JSON object: {findings}")
    findings = body.get("findings")
    if not isinstance(findings, str) or not findings.strip():
        return _refuse(400, "findings is empty: say what the check found, so the team can fix it")
    if len(findings) > _FINDINGS_MAX_CHARS:
        return _refuse(400, f"findings is longer than {_FINDINGS_MAX_CHARS} characters")
    return findings


def _settled(catalog: Path, cid: str, only: str) -> web.Response | tuple[dict[str, Any], str]:
    """A handed-in project's record and latest hand-in, or the 404 that says it is not one."""
    folder = catalog / _CONVERSATIONS
    own = folder / f"{cid}.json"  # on Windows "c:x" names a file somewhere else: only this folder's own file counts
    record = thomas_project.settled_record(catalog, cid) if own.parent == folder and own.name == f"{cid}.json" else None
    sid = str((record or {}).get("submission") or "")
    if record is None or not _SUBMISSION_ID.fullmatch(sid):
        return _refuse(404, f"that is not a Thomas project handed in to your card: {only}")
    return record, sid


def _own_file(folder: Path, cid: str) -> Path | None:
    own = folder / f"{cid}.json"
    return own if own.parent == folder and own.name == f"{cid}.json" else None


def _stop_unstamped(cid: str, execution_id: str, going: bool, stopped: bool) -> web.Response:
    return web.json_response(
        {
            "ok": False,
            "conversation_id": cid,
            "execution_id": execution_id,
            "detail": "the stop is not stamped on its conversation and holds in this server only until it restarts",
            "stopped": True,
            "run_was_going": going,
            "run_stopped": stopped,
            "stamped": False,
        },
        status=409,
    )


def _stop_project_prepare(cid: str) -> tuple[web.Response | None, Path | None, Path | None, str]:
    """Look up the green and refuse stops of handed-in or unreadable projects off the event loop."""
    catalog = thomas_project._catalog_root()
    folder = catalog / _CONVERSATIONS
    own = _own_file(folder, cid)
    if own is not None and own.is_file():
        try:
            record = read_record(own)
        except (OSError, ValueError):
            record = None
        if isinstance(record, dict) and _project(record).get("execution_id"):
            project = _project(record)
            sid = str(project.get("submission") or (project.get("retirement") or {}).get("submission") or "")
            if sid and _SUBMISSION_ID.fullmatch(sid):
                if self_change_status.being_handed_in(cid):
                    return (
                        _refuse(409, f"{sid} is being checked to be handed in again: wait for that, then send it back"),
                        None,
                        None,
                        "",
                    )
                if (self_change_status.read_verdict(sid) or {}).get("status") == "landed":
                    return (
                        _refuse(409, f"{sid} already landed: there is no checked change to send back"),
                        None,
                        None,
                        "",
                    )
                if (green_handoff.inbox_dir() / sid).exists():
                    return (
                        _refuse(
                            409, f"{sid} is still in the promoter's inbox: wait for its verdict, then send it back"
                        ),
                        None,
                        None,
                        "",
                    )
            return (
                _refuse(
                    409,
                    f"{sid or 'this project'} was handed in to your card and left the inbox without landing; "
                    "nothing of it runs, and send-back returns it to its team",
                ),
                None,
                None,
                "",
            )

    work = None
    try:
        greens = _in_greens()
    except GreensUnreadable as exc:
        greens = exc.found
    for candidate, conversation in greens:
        if conversation.get("id") == cid:
            work = candidate
            break
    # The listing skips unreadable JSON. Find its own file without attempting a stop.
    if work is None:
        try:
            candidates = (green_checkout.green_root() / "work").iterdir()
            for candidate in candidates:
                path = _own_file(candidate / _CONVERSATIONS, cid)
                if path is not None and path.is_file():
                    work = candidate
                    break
        except FileNotFoundError:
            pass
    path = thomas_project._live_file(work, cid) if work is not None else None
    if path is not None and path != _own_file(work / _CONVERSATIONS, cid):
        path = None
    if path is None or not path.is_file():
        return _refuse(404, "that is not a Thomas project Thomas can stop"), None, None, ""
    try:
        conversation = read_record(path)
    except (OSError, ValueError, UnicodeError):
        return (
            web.json_response(
                {"ok": False, "detail": "its conversation could not be read and is not stamped", "stamped": False},
                status=409,
            ),
            None,
            None,
            "",
        )
    project = _project(conversation) if isinstance(conversation, dict) else {}
    execution_id = str(project.get("execution_id") or "")
    if not execution_id or conversation.get("id") != cid:
        return _refuse(404, "that is not a Thomas project Thomas can stop"), None, None, ""
    return None, work, path, execution_id


def _stop_project_mark(work: Path, catalog: Path, cid: str) -> bool:
    """Stamp the stop and clear the park without holding up aiohttp; keep clearing on write failure."""
    stamped_write = True
    try:
        thomas_project.request_stop(work, cid)
    except OSError:
        log.exception("could not stamp stop on Thomas project %s", cid)
        stamped_write = False
    try:
        autopilot_park.clear(work, catalog, cid)
    except OSError:
        log.exception("could not clear autopilot park for Thomas project %s", cid)
    return stamped_write


def _stop_project_stamped(path: Path, begun: datetime) -> bool:
    try:
        latest = read_record(path)
        stamp = latest.get("thomas_project", {}).get("stopped_at")
        moment = datetime.fromisoformat(stamp) if isinstance(stamp, str) else None
        return bool(moment and moment >= begun)
    except (OSError, ValueError, UnicodeError, TypeError, AttributeError):
        return False


async def _stop_project(app: web.Application, cid: str) -> web.Response:
    """Stop a live project without a Chat card, retaining the stop on its green conversation."""
    begun = datetime.now(timezone.utc)
    refused, work, path, execution_id = await asyncio.to_thread(_stop_project_prepare, cid)
    if refused is not None:
        return refused
    assert work is not None and path is not None
    catalog = thomas_project._catalog_root()
    slot = (app.get(APP_EVOLVE_AGENT_RUNS) or {}).get(cid)
    going = slot_active(slot) if slot else False
    stamped_write = await asyncio.to_thread(_stop_project_mark, work, catalog, cid)
    stopped = False
    if going:
        session = slot.get("session") if isinstance(slot, dict) else None
        run_id = session.get("run_id") if isinstance(session, dict) else None
        hook = app.get(APP_PRAXIS_STOP_CODE_RUN)
        if run_id and hook:
            stopped = bool(await hook(run_id))
    stamped = await asyncio.to_thread(_stop_project_stamped, path, begun)
    stamped = stamped and stamped_write
    app.setdefault("self_project_listing_slot", {})["dirty"] = True
    if not stamped:
        return _stop_unstamped(cid, execution_id, going, stopped)
    return web.json_response(
        {
            "ok": True,
            "conversation_id": cid,
            "execution_id": execution_id,
            "state": "stopped",
            "detail": "you stopped it",
            "stopped": True,
            "run_was_going": going,
            "run_stopped": stopped,
            "stamped": True,
        }
    )


def _green_of(record: dict[str, Any], cid: str) -> green_checkout.Green | None:
    green = green_checkout.find_green(str(record.get("execution_id") or ""))
    return green if green is not None and (green.work / _CONVERSATIONS / f"{cid}.json").is_file() else None


# Task 3g: why a hand-in with some other verdict does not go in again as it is.
_NOT_THIS_REFUSAL = {
    "landed": "already landed, so nothing goes in again: start a new project for a follow-up",
    "declined": "was declined at your card, so it does not go in again as it is: use send-back to return it to its team",
    "error": "ended in an error at the promoter: use send-back to return it to its team",
}


def _to_hand_in_again(catalog: Path, cid: str) -> web.Response | tuple[green_checkout.Green, str]:
    """The green and refused hand-in to hand in again, or the refusal that says why not. Only reads."""
    found = _settled(catalog, cid, "only a handed-in change goes in again")
    if isinstance(found, web.Response):
        return found
    record, sid = found
    if (green_handoff.inbox_dir() / sid).exists():
        return _refuse(409, f"{sid} is still in the promoter's inbox, so it has no verdict yet: wait for your card")
    verdict = self_change_status.read_verdict(sid) or {}
    files, status = self_change_status.uncommitted_files(verdict), str(verdict.get("status") or "")
    if not files:
        if self_change_status.dev_moved(verdict):
            why = "was refused because dev moved on, so its team must merge dev: use send-back to return it to its team"
        else:
            why = _NOT_THIS_REFUSAL.get(status) or (
                f"was refused, but not for the running copy's uncommitted work ({verdict.get('detail') or ''}): use "
                "send-back to return it to its team"
                if status == "refused"
                else "left the promoter's inbox with no verdict: use send-back to return it to its team"
            )
        return _refuse(409, f"{sid} {why}")
    green = _green_of(record, cid)
    if green is None:
        return _refuse(409, "its green copy is gone, so there is nothing to hand in again: start a new project instead")
    dirty = green_handoff.uncommitted_in_running_copy(green.execution_id, files)
    if dirty is None:
        return _refuse(409, "the running copy could not be read, so it is not known whether that work is committed")
    if dirty:
        still = ", ".join(dirty)
        return _refuse(409, f"the running copy still has uncommitted work in {still}: commit it, then hand it in again")
    return green, sid


async def _hand_in_again(app: Any, cid: str) -> web.Response:
    """Check what can be read now, claim the hand-in, and answer 202 while it is checked and handed in.

    The hand-in runs the check before your card, which may take up to an hour. It used to run inside this request,
    under the lock send-back shares; now the listing says "checking" until it is out, and then shows its hand-in."""
    catalog = thomas_project._catalog_root()
    found = await asyncio.to_thread(_to_hand_in_again, catalog, cid)
    if isinstance(found, web.Response):
        return found
    green, sid = found
    if not self_change_status.claim(cid):
        return _refuse(409, f"{sid} is already being checked and handed in again: wait for its card")
    self_change_status.hand_in_again_later(app, green.work, catalog, cid, sid)
    eid = green.execution_id
    body = {"ok": True, "conversation_id": cid, "execution_id": eid, "refused": sid, "state": "checking"}
    return web.json_response(body, status=202)


def _to_send_back(catalog: Path, cid: str) -> web.Response | tuple[green_checkout.Green, str]:
    """The green and hand-in a send-back starts from, or the refusal that says why it cannot go back. Only reads.

    The inbox and the verdicts are read where the server hands in and follows (``green_handoff.inbox_dir``,
    ``self_change_status.read_verdict``). The promoter writes a verdict before it moves a hand-in out of the
    inbox, and a hand-in it could not move would be promoted again, so one still there is refused, verdict or not.
    """
    found = _settled(catalog, cid, "only a handed-in change goes back")
    if isinstance(found, web.Response):
        return found
    record, sid = found
    if self_change_status.being_handed_in(cid):
        return _refuse(409, f"{sid} is being checked to be handed in again: wait for that, then send it back")
    if (self_change_status.read_verdict(sid) or {}).get("status") == "landed":
        return _refuse(409, f"{sid} already landed, so nothing goes back: start a new project for a follow-up")
    if (green_handoff.inbox_dir() / sid).exists():
        waiting = "is still in the promoter's inbox, so your card may be showing: answer or decline it first"
        return _refuse(409, f"{sid} {waiting}")
    green = _green_of(record, cid)
    if green is None:
        return _refuse(409, "its green copy is gone, so its team has nothing to fix: start a new project instead")
    return green, sid


async def _send_back(app: Any, cid: str, findings: str) -> web.Response:
    """Start the repair round through Autopilot's own path (``start_repair``), and answer only what happened.

    Build writes a run's first turn before it accepts the run, so a round still due afterwards never started: the
    answer then says so rather than ``ok``. A refusal from Build is in the issue log (``autopilot_start_refused``).
    """
    catalog = thomas_project._catalog_root()
    found = await asyncio.to_thread(_to_send_back, catalog, cid)
    if isinstance(found, web.Response):
        return found
    green, sid = found
    decision = await start_repair(app, green.work, catalog, cid, why=thomas_project.SENT_BACK, detail=findings, sid=sid)
    conversation = await asyncio.to_thread(forge_code_store.load_conversation, green.work, cid) or {}
    rounds = thomas_project.repairs_done(_project(conversation))
    if decision is None:
        spent = thomas_project.repairs_spent(conversation)
        if spent:
            successor = _project(conversation).get("successor")
            if isinstance(successor, dict) and successor.get("conversation_id"):
                return web.json_response({"ok": True, "successor": successor}, status=202)
            return _refuse(503, f"repair rounds spent; successor did not start: {spent}")
        return _refuse(500, "repair round did not start; the server log says why")
    if decision.action != "repair" or thomas_project.repair_due(conversation) is not None:
        refused = "Build refused its start (the issue log has its answer)"
        why = decision.reason if decision.action != "repair" else refused
        return _refuse(409, f"repair round {rounds} is stamped on it, but no run started: {why}")
    eid = green.execution_id
    log.info("Thomas project %s went back to its team in %s: repair round %d", cid, eid, rounds)
    return web.json_response({"ok": True, "conversation_id": cid, "execution_id": eid, "round": rounds})


def register_self_project_routes(app: web.Application, *, require_loopback: Callable[[web.Request], None]) -> None:
    """``POST`` and ``GET`` ``/api/self/projects``, ``POST {id}/send-back`` and ``POST {id}/hand-in-again``, all behind
    the server's loopback guard."""
    sending = asyncio.Lock()  # one send-back at a time: a second click must never stamp a second round
    listing_slot: dict[str, Any] = {}
    app["self_project_listing_slot"] = listing_slot

    async def start(request: web.Request) -> web.Response:
        requested_at = time.time()
        require_loopback(request)
        try:
            body = await request.json()
        except ValueError:  # json.JSONDecodeError and UnicodeDecodeError are both ValueErrors
            return _refuse(400, "the body is not JSON")
        checked = _checked(body)
        if isinstance(checked, web.Response):
            return checked
        ask, settings, chat = checked
        port = local_port(request)
        remember_port(request.app, port)  # the port Build runs report back to, learned the way Chat learns it
        if port <= 0:
            return _refuse(409, "the server's own port is not known yet; try again in a moment")
        found = long_requirements(ask)
        notice = long_requirements_notice(found) if found else ""
        meta = {"requested_at": requested_at, **({"chat_session_id": chat} if chat else {})}
        try:
            started = await _start_waiting_out_stalls(request.app, ask, settings, port, meta)
        except (thomas_project.ThomasProjectError, forge_code_projects.ForgeCodeProjectError) as exc:
            return _refuse(409, str(exc))
        listing_slot["dirty"] = True
        log.info("Thomas project %s started without Chat in %s", started["conversation_id"], started["execution_id"])
        fields = ("conversation_id", "execution_id", "project_root")
        answer = {"ok": True, **{key: started[key] for key in fields}}
        if found:
            answer.update(long_requirements=found, notice=notice)
        return web.json_response(answer)

    async def listing(request: web.Request) -> web.Response:
        require_loopback(request)
        catalog = thomas_project._catalog_root()
        report = await read_project_listing(listing_slot, catalog, lambda: _running(request.app), read_projects)
        return web.json_response(report, status=200 if report.get("ok") else 500)

    async def send_back(request: web.Request) -> web.Response:
        require_loopback(request)
        cid = request.match_info["conversation_id"]
        if not _CHAT_ID.fullmatch(cid):
            return _refuse(400, "that is not a conversation id")
        try:
            body = await request.json()
        except ValueError:  # json.JSONDecodeError and UnicodeDecodeError are both ValueErrors
            return _refuse(400, "the body is not JSON")
        findings = _findings(body)
        if isinstance(findings, web.Response):
            return findings
        port = local_port(request)
        remember_port(request.app, port)  # the port the round's Build run reports back to
        if port <= 0:
            return _refuse(409, "the server's own port is not known yet; try again in a moment")
        if request.app.get(APP_PRAXIS_START_CODE_RUN) is None:
            return _refuse(409, "no Build start hook is bound -- the server has not finished starting up")
        async with sending:
            return await _send_back(request.app, cid, findings)

    async def hand_in_again(request: web.Request) -> web.Response:
        require_loopback(request)
        cid = request.match_info["conversation_id"]
        if not _CHAT_ID.fullmatch(cid):
            return _refuse(400, "that is not a conversation id")
        remember_port(request.app, local_port(request))  # the port a repair round after its next verdict reports to
        async with sending:  # held only to read and claim: the claim keeps a second click from handing it in twice
            return await _hand_in_again(request.app, cid)

    async def stop(request: web.Request) -> web.Response:
        require_loopback(request)
        cid = request.match_info["conversation_id"]
        if not _CHAT_ID.fullmatch(cid):
            return _refuse(400, "that is not a conversation id")
        return await _stop_project(request.app, cid)

    app.router.add_post(PATH, start)
    app.router.add_get(PATH, listing)
    app.router.add_post(SEND_BACK_PATH, send_back)
    app.router.add_post(HAND_IN_AGAIN_PATH, hand_in_again)
    app.router.add_post(STOP_PATH, stop)


__all__ = [
    "GreensUnreadable",
    "HAND_IN_AGAIN_PATH",
    "PATH",
    "SEND_BACK_PATH",
    "STOP_PATH",
    "SETTINGS_KEYS",
    "list_projects",
    "read_projects",
    "register_self_project_routes",
    "running_projects",
]
