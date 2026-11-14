"""Drain admitted work before an owner-requested server restart.

The caller is responsible for authorizing the request before calling
``request_restart``. This module never treats a chat card as authorization.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any
from uuid import uuid4

from thomas.server import capacity_ledger, landed_code_reload, landed_code_resume
from thomas.server.app_keys import APP_RESTART_REQUESTED, APP_SHUTDOWN_EVENT

log = logging.getLogger(__name__)
APP_OWNER_RESTART = "owner_restart"
APP_OWNER_RESTART_TASK = "owner_restart_task"
POLL_S = 1.0
SERVER_GENERATION = uuid4().hex


def _state(app: Any) -> Any:
    return getattr(app, "_state", app)


def status(app: Any) -> dict[str, Any]:
    current = app.get(APP_OWNER_RESTART) or {}
    automatic = app.get(landed_code_reload.APP_LANDED_CODE_DRAIN) or app.get(landed_code_reload.APP_LANDED_CODE_CHECKS)
    if not current and isinstance(automatic, dict) and automatic:
        current = {**automatic, "restarting": True, "phase": automatic.get("phase") or "draining"}
    started = current.get("since")
    return {
        "restarting": bool(current.get("restarting")),
        "checks_running": current.get("checks_running"),
        "elapsed_s": max(0.0, time.monotonic() - started) if started is not None else 0.0,
        "phase": current.get("phase", "idle"),
        "generation": SERVER_GENERATION,
        "waiting_for": list(current.get("waiting_for") or ()),
        # Said plainly while the restart waits for checks: the Builds are still working (landed_code_reload).
        "words": current.get("words") or "",
        "notice": (app.get("landed_code_notice") or {}).get("notice"),
        "swap": app.get("landed_plugin_swap"),
        "swaps": list(app.get("landed_plugin_swaps") or ()),
    }


def request_restart(app: Any) -> dict[str, Any]:
    """Close check admission and start one drain; repeated requests share it.

    Build admission stays open while the checks already running finish (:func:`drain`); only then is it closed and are
    the Builds asked to yield. Until 2026-11-13 both happened here, and every Build sat idle while one check ran an hour.
    """
    current = app.get(APP_OWNER_RESTART)
    loop = asyncio.get_running_loop()
    state = _state(app)
    if current and current.get("restarting"):
        task = app.get(APP_OWNER_RESTART_TASK)
        if (task is None or task.done()) and not app[APP_SHUTDOWN_EVENT].is_set():
            state[APP_OWNER_RESTART_TASK] = loop.create_task(drain(app))
        return status(app)
    now = time.monotonic()
    generation = uuid4().hex
    current = {
        "restarting": True,
        "since": now,
        "generation": generation,
        "checks_running": None,
        "phase": "draining",
        "waiting_for": [],
    }
    from thomas.server.precard import workers

    workers.close_admission()
    landed = app.get(landed_code_reload.APP_LANDED_CODE_DRAIN)
    if isinstance(landed, dict) and landed.get("signalled"):
        current["yielding"] = True  # landed code already asked the Builds to yield: the drain goes on from there
    else:
        state.pop(landed_code_reload.APP_LANDED_CODE_DRAIN, None)
    state.pop(landed_code_reload.APP_LANDED_CODE_CHECKS, None)
    state[APP_OWNER_RESTART] = current
    # No Build gate and no signal here: Builds keep working while checks finish. Once none runs, the drain sets the
    # gate, first acquires the launch lock (a start inside it may not yet be registered) and remembers every run.
    state[APP_OWNER_RESTART_TASK] = loop.create_task(drain(app))
    return status(app)


async def cancel_restart(app: Any) -> dict[str, Any]:
    """Drop a restart that was asked for: admission reopens and held work resumes. Running checks are untouched.

    A restart waits for every running check, which can take an hour, and meanwhile new Build starts are held. You
    must be able to say "not now" instead of waiting that out.
    """
    current = app.get(APP_OWNER_RESTART)
    if current and current.get("restarting") and current.get("phase") != "restarting":
        from thomas.server.precard import workers

        state = _state(app)
        state.pop(APP_OWNER_RESTART, None)
        task = app.get(APP_OWNER_RESTART_TASK)
        if task is not None and not task.done():
            task.cancel()
        state.pop(APP_OWNER_RESTART_TASK, None)
        workers.open_admission()
        landed_code_reload._clear_drain(app)
        await landed_code_resume.resume(app)
    return status(app)


def _strict_checks(rows: Any) -> int:
    """Reject malformed ledger snapshots rather than interpreting them as empty."""
    if not isinstance(rows, list):
        raise ValueError("capacity ledger did not return a list")
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("state"), str):
            raise ValueError("capacity ledger returned an invalid row")
        if not isinstance(row.get("kind"), str) or not isinstance(row.get("id"), str):
            raise ValueError("capacity ledger returned a row without kind or id")
    return landed_code_reload._admitted_checks(rows)


async def _checks_left(app: Any, current: dict[str, Any]) -> list[str]:
    """The checks still running, said on the report with the plain words that Builds keep working meanwhile."""
    waiting = await landed_code_reload.waiting_work(app)
    checks = _strict_checks(await asyncio.to_thread(capacity_ledger.rows))
    current["checks_running"] = checks
    checking = landed_code_reload.checks_in(waiting)
    if checks and landed_code_reload.CHECK_WORKERS not in checking:
        checking.append(landed_code_reload.CHECK_WORKERS)
    if checking:
        current.update(
            phase=landed_code_reload.CHECKS_FINISHING,
            waiting_for=checking,
            words=landed_code_reload.BUILDS_KEEP_WORKING,
        )
    return checking


async def drain(app: Any) -> None:
    """Wait for running checks with every Build working, then close Build admission until work and the ledger clear.

    Running checks are never cancelled, and no new check starts (``request_restart`` closed check admission). Only once
    no check runs are the Builds asked to yield; from then on admission stays closed until the restart. A failed read
    or drain operation is retried, rather than treating uncertainty as idle.
    """
    current = app.get(APP_OWNER_RESTART)
    if not current or not current.get("restarting"):
        return
    generation = current["generation"]
    gate = app.get(landed_code_reload.APP_LANDED_CODE_DRAIN)
    if not isinstance(gate, dict) or gate.get("head") != generation:
        gate = {"head": generation, "since": current["since"], "owner_restart": True}
    shutdown = app[APP_SHUTDOWN_EVENT]
    while not shutdown.is_set() and app.get(APP_OWNER_RESTART) is current:
        try:
            if not current.get("yielding"):
                checking = await _checks_left(app, current)
                if shutdown.is_set() or app.get(APP_OWNER_RESTART) is not current:
                    return
                if checking:
                    await asyncio.sleep(POLL_S)
                    continue
                current["yielding"] = True  # no check runs: the Builds yield now, as before
                current["phase"] = "draining"
                current.pop("words", None)
            _state(app)[landed_code_reload.APP_LANDED_CODE_DRAIN] = gate
            # Synchronize with starts already inside the launch lock before
            # signalling or deciding there are no active Builds to preserve.
            await landed_code_resume.finish_drain(app)
            if shutdown.is_set() or app.get(APP_OWNER_RESTART) is not current:
                return
            if app.get(landed_code_reload.APP_LANDED_CODE_DRAIN) is not gate:
                continue
            landed_code_reload._signal_runs(
                gate,
                generation,
                time.monotonic() - current["since"],
                list(landed_code_reload.active_work(app)),
            )
            waiting = await landed_code_reload.waiting_work(app)
            # waiting_work treats a ledger read failure as zero; independently
            # verify the ledger before considering shutdown.
            rows = await asyncio.to_thread(capacity_ledger.rows)
            checks = _strict_checks(rows)
            if shutdown.is_set() or app.get(APP_OWNER_RESTART) is not current:
                return
            if app.get(landed_code_reload.APP_LANDED_CODE_DRAIN) is not gate:
                continue
            current["checks_running"] = checks
            current["waiting_for"] = list(waiting)
            if checks and landed_code_reload.CHECK_WORKERS not in current["waiting_for"]:
                current["waiting_for"].append(landed_code_reload.CHECK_WORKERS)
            if waiting or checks:
                current["phase"] = "draining"
            else:
                # No asynchronous gap between the final in-memory snapshot and
                # requesting shutdown. Check admission must also be gated by the
                # caller/integration for the ledger snapshot to remain stable.
                active = landed_code_reload.active_work(app)
                current["waiting_for"] = list(active)
                if active:
                    current["phase"] = "draining"
                else:
                    _state(app)[APP_RESTART_REQUESTED] = True
                    current["phase"] = "restarting"
                    shutdown.set()
                    return
        except asyncio.CancelledError:
            raise
        except (OSError, RuntimeError, ValueError, TypeError, KeyError):  # the ledger, a drain step or a bad snapshot
            current["checks_running"] = None
            current["waiting_for"] = []
            current["phase"] = "waiting"
            log.exception("owner restart drain could not verify work; keeping server running")
        await asyncio.sleep(POLL_S)
