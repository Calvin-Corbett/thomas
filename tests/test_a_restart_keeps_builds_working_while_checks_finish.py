"""A restart waits for running checks with every Build still working, and only then asks the Builds to yield.

On 2026-11-13 a restart yielded every running Build within minutes and then waited 45 to 60 minutes for one check
before your card: the whole fleet sat idle. You said "dude again just thoma swiaitng oin brojken checks". Now, while
a check runs, Builds keep working and new ones may start; no new check starts, and a hand-in that arrives is held
for after the restart, with no strike and without counting as a check that could not run.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from tests import hand_in_hold_support as support
from thomas.server import (
    autopilot_enough,
    autopilot_hold_tick,
    autopilot_restart,
    capacity_ledger,
    hand_in_hold,
    self_change_status,
    thomas_project,
)
from thomas.server import landed_code_reload as reload
from thomas.server import owner_restart as restart
from thomas.server.app_keys import APP_LOCAL_PORT, APP_RESTART_REQUESTED, APP_SHUTDOWN_EVENT
from thomas.server.precard import workers
from thomas.server.routes import evolve_agent_autopilot as route

CHECK = {"id": "check:green-1", "kind": "check", "state": "admitted"}
LANDED = ("old", "new", ["thomas/not_loaded.py"])


@pytest.fixture(autouse=True)
def _own_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(capacity_ledger.ROOT_ENV, str(tmp_path / "ledger"))
    monkeypatch.setenv("THOMAS_STEP_LOG_DIR", str(tmp_path / "metrics"))
    monkeypatch.setattr(autopilot_hold_tick, "_previous_listener_gone", lambda _port: False)


@pytest.fixture
def owner(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """An owner restart whose work is read from ``world``: what runs in memory and what the ledger lists."""
    world: dict[str, Any] = {"work": ["Build run", "check threads"], "rows": [dict(CHECK)], "signals": []}

    async def finish(_app: Any) -> None:
        return None

    async def waiting(_app: Any) -> tuple[str, ...]:
        return tuple(world["work"])

    monkeypatch.setattr(restart.landed_code_resume, "finish_drain", finish)
    monkeypatch.setattr(restart.landed_code_resume, "resume", finish)
    monkeypatch.setattr(reload, "waiting_work", waiting)
    monkeypatch.setattr(reload, "active_work", lambda _app: tuple(world["work"]))
    monkeypatch.setattr(reload, "_signal_runs", lambda *args: world["signals"].append(args))
    monkeypatch.setattr(restart.capacity_ledger, "rows", lambda: [dict(row) for row in world["rows"]])
    monkeypatch.setattr(restart, "POLL_S", 0.001)
    world["app"] = {APP_SHUTDOWN_EVENT: asyncio.Event()}
    return world


async def _until(predicate: Any) -> None:
    for _ in range(400):
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("the restart never reached the expected state")


@pytest.mark.asyncio
async def test_an_owner_restart_waits_for_checks_with_builds_still_working(owner: dict[str, Any]) -> None:
    app = owner["app"]
    restart.request_restart(app)
    task = app[restart.APP_OWNER_RESTART_TASK]
    try:
        await _until(lambda: restart.status(app)["phase"] == reload.CHECKS_FINISHING)
        await asyncio.sleep(0.03)  # many polls while the check runs
        report = restart.status(app)
        assert not owner["signals"], "no Build is asked to yield while a check runs"
        assert reload.APP_LANDED_CODE_DRAIN not in app, "new Builds may start while the check finishes"
        assert workers.admission_closed(), "no new check starts while the restart is pending"
        assert report["restarting"] and report["checks_running"] == 1
        assert set(report["waiting_for"]) == {"check threads", reload.CHECK_WORKERS}
        assert "Build run" not in report["waiting_for"]
        assert "Builds keep working" in report["words"]

        owner["work"], owner["rows"] = ["Build run"], []  # the check ended
        await _until(lambda: bool(owner["signals"]))
        assert app[reload.APP_LANDED_CODE_DRAIN]["owner_restart"], "now new starts are held and Builds yield"
        assert restart.status(app)["phase"] == "draining" and not restart.status(app)["words"]
        assert not app[APP_SHUTDOWN_EVENT].is_set(), "it still waits for the Builds to yield"

        owner["work"] = []  # the Builds yielded
        await asyncio.wait_for(task, 2)
        assert app[APP_SHUTDOWN_EVENT].is_set() and app[APP_RESTART_REQUESTED] is True
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        workers.open_admission()


@pytest.mark.asyncio
async def test_cancel_while_checks_finish_leaves_every_build_alone(owner: dict[str, Any]) -> None:
    app = owner["app"]
    restart.request_restart(app)
    task = app[restart.APP_OWNER_RESTART_TASK]
    await _until(lambda: restart.status(app)["phase"] == reload.CHECKS_FINISHING)

    after = await restart.cancel_restart(app)
    await asyncio.gather(task, return_exceptions=True)

    assert after["restarting"] is False and after["phase"] == "idle"
    assert not workers.admission_closed(), "checks may start again"
    assert reload.APP_LANDED_CODE_DRAIN not in app and not owner["signals"]
    assert not app[APP_SHUTDOWN_EVENT].is_set()
    assert owner["rows"] == [CHECK], "the running check is never touched"


@pytest.fixture
def landing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    """A landed kernel change that needs the full restart, once landed code has waited its longest for Builds."""
    world: dict[str, Any] = {"work": ("Build run", "check threads")}
    monkeypatch.setattr(reload, "resolve_thomas_data_dir", lambda: tmp_path)
    monkeypatch.setattr(reload.cage_shell, "cage_root", lambda: tmp_path)
    monkeypatch.setattr(reload.owner_desk, "enabled", lambda: True)
    monkeypatch.setattr(reload.workers, "generation_stopping", lambda: False)
    monkeypatch.setattr(reload, "active_work", lambda _app: tuple(world["work"]))
    monkeypatch.setattr(reload, "BUILD_HOLD_S", 0.0)
    world["app"] = {APP_SHUTDOWN_EVENT: asyncio.Event()}
    return world


async def _look(world: dict[str, Any], at: float, quiet: float | None = None, landed: Any = LANDED) -> float | None:
    return await reload.check_once(world["app"], quiet, at, work=tuple(world["work"]), landed=landed)


@pytest.mark.asyncio
async def test_landed_code_waits_for_checks_without_stopping_builds(landing: dict[str, Any]) -> None:
    app = landing["app"]
    try:
        for at in (0.0, reload.RUN_YIELD_AFTER_S + 60):  # no cap: a running check never makes the Builds yield
            assert await _look(landing, at) is None
            assert not reload.drain_signal_path().exists(), "no Build is asked to yield while a check runs"
            assert reload.APP_LANDED_CODE_DRAIN not in app, "new Builds may start while the check finishes"
            assert workers.admission_closed(), "no new check starts while the restart is pending"
        report = restart.status(app)
        assert report["restarting"] and report["phase"] == reload.CHECKS_FINISHING
        assert report["waiting_for"] == ["check threads"] and "Builds keep working" in report["words"]

        landing["work"] = ("Build run",)  # the check ended
        assert await _look(landing, reload.RUN_YIELD_AFTER_S + 90) is None
        assert reload.drain_signal_path().read_text(encoding="utf-8").strip() == "new", "now the Builds yield"
        assert app[reload.APP_LANDED_CODE_DRAIN]["head"] == "new"
        assert reload.APP_LANDED_CODE_CHECKS not in app

        landing["work"] = ()  # the Builds yielded
        quiet = await _look(landing, reload.RUN_YIELD_AFTER_S + 120)
        await _look(landing, reload.RUN_YIELD_AFTER_S + 120 + reload.RELOAD_QUIET_S, quiet)
        assert app[APP_SHUTDOWN_EVENT].is_set()
    finally:
        workers.open_admission()


@pytest.mark.asyncio
async def test_checks_open_again_when_the_landing_goes_away(landing: dict[str, Any]) -> None:
    app = landing["app"]
    try:
        await _look(landing, 0.0)
        assert workers.admission_closed()
        await _look(landing, 30.0, landed=None)  # the restart happened elsewhere, or the change went away
        assert not workers.admission_closed() and reload.APP_LANDED_CODE_CHECKS not in app
        assert not restart.status(app)["restarting"]
    finally:
        workers.open_admission()


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> support.Project:
    return support.make_project(tmp_path, monkeypatch)


def test_a_hand_in_during_a_pending_restart_waits_for_it_without_a_strike(
    project: support.Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    work, catalog, cid = project
    counted: list[Any] = []
    scheduled: list[dict[str, Any]] = []
    monkeypatch.setattr(thomas_project, "settle_if_finished", lambda *_a, **_k: pytest.fail("a check started"))
    monkeypatch.setattr(autopilot_enough, "unavailable_stalled", lambda *a, **_k: counted.append(a) or False)
    monkeypatch.setattr(autopilot_restart, "_runners_of", lambda _cid: ([], []))
    monkeypatch.setattr(self_change_status, "being_handed_in", lambda _cid: False)
    monkeypatch.setattr(autopilot_hold_tick, "_schedule", lambda _app, held, _catalog: scheduled.append(held) or True)

    async def during_the_restart() -> None:
        workers.close_admission()
        try:
            await route._settle_thomas_project(work, catalog, cid, app={APP_LOCAL_PORT: 8899})
            assert await autopilot_hold_tick.tick({APP_LOCAL_PORT: 8899}, catalog) == [], "not retried while pending"
        finally:
            workers.open_admission()

    asyncio.run(during_the_restart())
    held = support.row(project)
    assert held is not None
    assert (held["state"], held["step"], held["tries"], held["strikes"]) == ("held", "check", 0, 0)
    assert "restart" in held["why"] and held["next_at"] <= hand_in_hold.clock(), "due as soon as the restart is over"
    assert not counted, "a restart is not a check that could not run"
    assert not self_change_status.being_handed_in(cid)

    assert support.tick(project) == [cid], "the next server tries it at once"
    assert (scheduled[0]["state"], scheduled[0]["tries"], scheduled[0]["strikes"]) == ("checking", 1, 0)
