"""Carry a Code-page steer after its stopped Build turn is recorded."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from thomas.forge.anvil import forge_code_projects
from thomas.server import thomas_project

from . import evolve_agent_autopilot as autopilot
from .evolve_agent_run_state import (
    APP_EVOLVE_AGENT_DRAIN,
    APP_EVOLVE_AGENT_RUNS,
    APP_EVOLVE_AGENT_SESSION,
    slot_active,
)
from .evolve_agent_runtime import _default_repo_root, _recording_task

log = logging.getLogger(__name__)
STEER_WAIT_S = 600
STEER_GRACE_S = 30
_POLL_S = 1
_watchers: set[asyncio.Task[None]] = set()


def watch_page_steer(app: Any, session: dict[str, Any] | None, drain: Any, text: str) -> None:
    """Schedule a follow-up without changing the steer route's response or stop."""
    if not isinstance(session, dict):
        return
    cid = str(session.get("conversation_id") or "")
    project = session.get("project_root")
    if not cid or not project:
        return
    run_id = str(session.get("run_id") or "")
    watcher = asyncio.create_task(_after_stop(app, Path(project), cid, run_id, text, drain))
    _watchers.add(watcher)
    watcher.add_done_callback(_watcher_done)


def _watcher_done(watcher: asyncio.Task[None]) -> None:
    _watchers.discard(watcher)
    if not watcher.cancelled():
        try:
            watcher.result()
        except Exception:
            log.exception("page steer follow-up failed")


def _read_conversation(project_root: Path, cid: str) -> tuple[Path, dict[str, Any] | None]:
    # The Code catalog holds requested settings even when the project is elsewhere.
    catalog_root = _default_repo_root()
    if not forge_code_projects.conversation_metadata(catalog_root, cid):
        catalog_root = project_root
    return catalog_root, autopilot._load_joined_conversation(project_root, catalog_root, cid)


def _subsequent_run(app: Any, cid: str, stopped_id: str, turns: list[dict[str, Any]]) -> tuple[bool, str]:
    """Find a new run even if it has already finished and left the live registry."""
    for turn in reversed(turns):
        if turn.get("role") == "user":
            return True, str(turn.get("text") or "")
    slot = (app.get(APP_EVOLVE_AGENT_RUNS) or {}).get(cid) or {}
    session = slot.get("session") or {}
    if session.get("run_id") and str(session["run_id"]) != stopped_id:
        return True, str(session.get("message") or "")
    session = app.get(APP_EVOLVE_AGENT_SESSION) or {}
    if session.get("conversation_id") == cid and session.get("run_id") and str(session["run_id"]) != stopped_id:
        return True, str(session.get("message") or "")
    return False, ""


async def _after_stop(
    app: Any,
    project_root: Path,
    cid: str,
    stopped_id: str,
    text: str,
    drain: Any,
) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + STEER_WAIT_S
    task = _recording_task(drain)
    catalog_root, conversation = await asyncio.to_thread(_read_conversation, project_root, cid)
    requested = ((conversation or {}).get("settings") or {}).get("requested") or {}
    if requested.get("autonomy_level") != autopilot.AUTOPILOT:
        return  # The Code page owns the next turn outside Autopilot.
    turns = (conversation or {}).get("turns") or []
    baseline = len(turns)
    # The recorder and page can both finish before our first off-thread read.
    # Keep the stopped turn and anything after it visible to the follow-up check.
    for index in range(len(turns) - 1, -1, -1):
        turn = turns[index]
        if (
            turn.get("role") == "agent"
            and turn.get("outcome") == "stopped"
            and str(turn.get("run_id") or stopped_id) == stopped_id
        ):
            baseline = index
            break
    # A pending recorder wakes the watcher promptly; otherwise poll at most once a second.
    next_read = loop.time() + _POLL_S
    recorder_woken = False
    recorded_in_time = False
    while loop.time() < deadline:
        if task is not None and task.done() and not recorder_woken:
            recorder_woken = True
            next_read = min(next_read, loop.time())
        delay = min(max(0, next_read - loop.time()), max(0, deadline - loop.time()))
        if task is not None and not task.done() and isinstance(task, asyncio.Future):
            await asyncio.wait({task}, timeout=delay)
        else:
            await asyncio.sleep(delay)
        if loop.time() >= deadline:
            break
        conversation = await asyncio.to_thread(autopilot._load_joined_conversation, project_root, catalog_root, cid)
        turns = (conversation or {}).get("turns") or []
        recorded = any(turn.get("role") == "agent" for turn in turns[baseline:]) or any(
            turn.get("role") == "agent" and turn.get("run_id") == stopped_id for turn in turns if stopped_id
        )
        if recorded and (task is None or task.done()):
            recorded_in_time = True
            await asyncio.sleep(STEER_GRACE_S)
            break
        next_read = loop.time() + _POLL_S

    conversation = await asyncio.to_thread(autopilot._load_joined_conversation, project_root, catalog_root, cid)
    turns = (conversation or {}).get("turns") or []
    # Only inspect user turns added after the stop; the original request may itself quote the steer.
    new_run, message = _subsequent_run(app, cid, stopped_id, turns[baseline:])
    if new_run and text in message:
        log.info("page steer carried by run: conversation %s", cid)
        return
    thomas_project.hold_steer(cid, text)
    slot = (app.get(APP_EVOLVE_AGENT_RUNS) or {}).get(cid)
    if not slot_active(slot) and recorded_in_time and conversation is not None:
        await autopilot._start_steered_round(app, conversation, cid, catalog_root)
        if not thomas_project.held_steers(cid):
            log.info("page steer started its own round: conversation %s", cid)
            return
    log.info("page steer held: conversation %s", cid)
