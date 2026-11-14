"""Carry yielded Build runs on when a landed-code drain ends without shutdown."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.core import machine_capacity
from thomas.server import autopilot_park, autopilot_restart, thomas_project
from thomas.server.app_keys import APP_RESTART_REQUESTED, APP_SHUTDOWN_EVENT
from thomas.server.landed_code_runs import APP_DRAIN_RUNS, DrainRun, track_start  # noqa: F401
from thomas.server.precard import workers
from thomas.server.routes.evolve_agent_run_state import (
    APP_EVOLVE_AGENT_CONVO,
    APP_EVOLVE_AGENT_LOCK,
    APP_EVOLVE_AGENT_RUNS,
    APP_EVOLVE_AGENT_SESSION,
    APP_EVOLVE_AGENT_TASK,
    active_code_runs,
)

log = logging.getLogger(__name__)


def cancel(app: Any, run_id: str) -> None:
    """Drop a Stop request's yielded run even after its inactive slot was pruned."""
    pending = app.get(APP_DRAIN_RUNS) or {}
    for cid, run in list(pending.items()):
        if run_id and run.run_id == run_id:
            pending.pop(cid, None)


def _stopped(run: DrainRun) -> bool:
    return bool(getattr(run.proc, "thomas_stop_requested", False))


def remember(app: Any) -> None:
    """Keep run identities before completed slots can be pruned from the registry."""
    pending = app.setdefault(APP_DRAIN_RUNS, {})
    active = active_code_runs(app)
    slots = dict(app.get(APP_EVOLVE_AGENT_RUNS) or {})
    cid = str(app.get(APP_EVOLVE_AGENT_CONVO) or "")
    if cid and cid not in slots:
        session = app.get(APP_EVOLVE_AGENT_SESSION) or {}
        slots[cid] = {"session": {**session, "proc": session.get("proc") or app.get(APP_EVOLVE_AGENT_TASK)}}
    for cid, slot in slots.items():
        session = slot.get("session") or {}
        root, run_id = session.get("project_root"), session.get("run_id")
        if root and run_id and active.get(str(cid)) == str(run_id):
            pending[str(cid)] = DrainRun(
                Path(root), str(run_id), str(session.get("request_id") or ""), session.get("proc")
            )


async def finish_drain(app: Any) -> None:
    """Wait for already-admitted starts before taking the final drain snapshot."""
    lock = app.get(APP_EVOLVE_AGENT_LOCK)
    if lock is None:
        remember(app)
    else:
        async with lock:
            remember(app)


def _yielded(catalog_root: Path, cid: str, run: DrainRun) -> autopilot_restart.Interrupted | None:
    from thomas.server.routes.evolve_agent_receipts import _action_receipt

    receipt = _action_receipt(catalog_root, "run", run.request_id) if run.request_id else None
    if receipt and (
        receipt.get("state") == "persistence_failed"
        or (receipt.get("persistence") or {}).get("persistence_confirmed") is False
    ):
        raise OSError(f"drain-yielded result is not durably saved for {cid}")
    conversation = thomas_project._read_live(run.project_root, catalog_root, cid)
    if conversation is None:
        raise OSError(f"could not read drain-yielded conversation {cid}")
    turns = autopilot_restart._turns(conversation)
    if not _matches(turns, run):
        return None
    turn = turns[-2]
    project = conversation.get("thomas_project") or {}
    return autopilot_restart.Interrupted(
        cid=cid,
        project_root=run.project_root,
        run_id=run.run_id,
        turn=turn,
        started_at=autopilot_park._turn_time(turn) or 0.0,
        thomas_project=bool(project),
        chat=str(project.get("chat_session_id") or ""),
    )


def _can_resume(app: Any) -> bool:
    shutdown = app.get(APP_SHUTDOWN_EVENT)
    owner_restart = app.get("owner_restart") or {}
    return (
        not app.get("landed_code_drain")
        and not owner_restart.get("restarting")
        and not app.get(APP_RESTART_REQUESTED)
        and not (isinstance(shutdown, asyncio.Event) and shutdown.is_set())
        and not workers.generation_stopping()
    )


def _matches(turns: list[dict[str, Any]], run: DrainRun) -> bool:
    return bool(
        len(turns) >= 2
        and turns[-1].get("role") == "agent"
        and turns[-1].get("outcome") == "reload_yielded"
        and turns[-1].get("run_id") == run.run_id
        and turns[-2].get("role") == "user"
        and turns[-2].get("request_id", "") == run.request_id
    )


def _gate_admit(app: Any, catalog: Path, cid: str, run: DrainRun, message: str) -> bool:
    if not _can_resume(app) or _stopped(run) or (app.get(APP_DRAIN_RUNS) or {}).get(cid) is not run:
        return False
    conversation = thomas_project._read_live(run.project_root, catalog, cid)
    if conversation is None:
        raise OSError(f"could not re-read drain-yielded conversation {cid}")
    turns = autopilot_restart._turns(conversation)
    return bool(
        not thomas_project.stop_requested(conversation)
        and _matches(turns[:-1], run)
        and turns[-1].get("role") == "user"
        and turns[-1].get("text") == thomas_project.steering_message(thomas_project.held_steers(cid), message)
    )


async def _admit(app: Any, catalog: Path, cid: str, run: DrainRun) -> bool:
    pending = app.get(APP_DRAIN_RUNS) or {}
    if not _can_resume(app) or _stopped(run) or active_code_runs(app).get(cid) or pending.get(cid) is not run:
        return False
    conversation = await asyncio.to_thread(thomas_project._read_live, run.project_root, catalog, cid)
    if conversation is None:
        raise OSError(f"could not re-read drain-yielded conversation {cid}")
    return bool(
        _can_resume(app)
        and not _stopped(run)
        and not active_code_runs(app).get(cid)
        and pending.get(cid) is run
        and not thomas_project.stop_requested(conversation)
        and _matches(autopilot_restart._turns(conversation), run)
    )


async def resume(app: Any) -> None:
    """Retry saved yields on watcher ticks, including recording and capacity waits."""
    from thomas.server.routes import evolve_agent_autopilot as ap

    pending = app.get(APP_DRAIN_RUNS)
    if not pending or not _can_resume(app):
        return
    catalog_root = Path(thomas_project._catalog_root())
    for cid, run in list(pending.items()):
        if not _can_resume(app):
            return
        if pending.get(cid) is not run:
            continue
        active_run = active_code_runs(app).get(cid)
        if _stopped(run) or (active_run and active_run != run.run_id):
            pending.pop(cid, None)
            continue
        if active_run:
            continue
        try:
            item = await asyncio.to_thread(_yielded, catalog_root, cid, run)
            # A restart can begin while the conversation is being read. Do not
            # discard a saved yield or start recovery across that boundary.
            if not _can_resume(app):
                return
            if item is None:
                if pending.get(cid) is run:
                    pending.pop(cid, None)
                continue
            if machine_capacity.admission_refusal(len(active_code_runs(app))) or autopilot_restart._cage_down():
                continue
            # Preserve the existing resume marker, so repair/goal parsing still unwraps the stopped request.
            message = (
                f"{ap.RESTART_PREFIX} after the landed-code drain cleared without a reload. "
                "The last Build run yielded for that drain. Inspect the work already in this folder, "
                "then carry on until the goal is met and its checks pass.\n\n"
                f"{ap.RESTART_MARK}{ap.run_text(item.turn)}"
            )
            result, why = await autopilot_restart._carry_on(
                app,
                catalog_root,
                item,
                observed_at=time.time(),
                message=message,
                can_start=lambda: _admit(app, catalog_root, cid, run),
                gate_guard=lambda: _gate_admit(app, catalog_root, cid, run, message),
            )
            if not _can_resume(app):
                return
            if result not in ("retry", "read_retry", "busy"):
                if pending.get(cid) is run:
                    pending.pop(cid, None)
                log.info("landed-code drain recovery %s: %s %s", cid, result, why)
        except (OSError, ValueError, RuntimeError, sqlite3.Error):
            log.exception("could not resume drain-yielded Build run %s; will retry", cid)
