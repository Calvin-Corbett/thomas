"""An overnight stop does not strand a Thomas project: a run that stopped with the server is carried on, once.

Each server records its life (``autopilot_silence``). An unfinished Autopilot run carries on
regardless of how long the server was off, unless it went quiet during the prior server's life
or that server deliberately left it stopped. Stubbed as in the restart tests this file shares
its fixtures with: Build's start hook, and nothing else.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests.test_a_restart_does_not_stop_a_thomas_project import (  # noqa: F401 -- isolated is an autouse fixture
    _app,
    _stopped_run,
    isolated,
)
from thomas.forge.anvil import forge_code_projects, forge_code_store
from thomas.server import autopilot_silence, green_handoff, thomas_project
from thomas.server.app_keys import APP_LOCAL_PORT
from thomas.server.autopilot_silence import Life
from thomas.server.praxis.launch import APP_PRAXIS_START_CODE_RUN
from thomas.server.precard import review
from thomas.server.routes import evolve_agent_autopilot as ap
from thomas.server.routes.evolve_agent_runtime import _transcript_path

HOUR = 3600.0


def _restart() -> Any:
    from thomas.server import autopilot_restart

    return autopilot_restart


def _heard(p: SimpleNamespace, hours_before_boot: float, run_id: str = "run-before") -> Path:
    """The stopped server's drain last wrote the run's transcript ``hours_before_boot`` before this server started."""
    path = _transcript_path(p.catalog, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"type": "assistant", "text": "editing thomas/tools/registry.py"}\n', encoding="utf-8")
    moment = p.booted - hours_before_boot * HOUR
    os.utime(path, (moment, moment))
    return path


def _written(p: SimpleNamespace, hours_before_boot: float) -> None:
    """The project's conversation file was last written when its run started, ``hours_before_boot`` ago."""
    moment = p.booted - hours_before_boot * HOUR
    os.utime(thomas_project._live_file(p.root, p.cid), (moment, moment))


def _server_before(p: SimpleNamespace, booted: float, alive: float, **marks: frozenset[str]) -> None:
    """What the server before this one recorded: it started ``booted`` hours before this one and was last alive
    ``alive`` hours before it."""
    life = Life(p.booted - booted * HOUR, p.booted - alive * HOUR, **marks)
    autopilot_silence.record_life(p.catalog, life, None)


@pytest.fixture
def card(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Your card's two doors: a hand-in and the second look. A carry-on only starts a Build run, so neither opens."""
    opened: list[str] = []
    monkeypatch.setattr(green_handoff, "settle", lambda *a, **k: opened.append("hand-in"))
    monkeypatch.setattr(review, "second_look", lambda *a, **k: opened.append("second look"))
    return opened


@pytest.mark.asyncio
async def test_the_09_29_overnight_stop_is_carried_on_once(tmp_path: Path, card: list[str]) -> None:
    """09-29: the run started 9.5 hours before the boot, and its transcript was last written 9.2 hours before it,
    when the server stopped for the night."""
    p = _stopped_run(tmp_path, ago=9.5 * HOUR)
    _written(p, 9.5)
    _heard(p, 9.2)
    _server_before(p, booted=14, alive=9.15)
    restart, app = _restart(), _app(p.catalog, starts := [])

    restart.survey(p.catalog, p.booted)  # this server started: until its run starts, the project is not "ended"
    assert thomas_project.project_phase(p.root, p.catalog, p.cid) == ("waiting", restart.CARRYING_ON)
    report = await restart.resume_interrupted(app, p.catalog, booted=p.booted)

    assert report["resumed"] == [p.cid] and len(starts) == 1, report
    assert starts[0]["message"].startswith(ap.RESTART_PREFIX), "carried on as a restart, with its goal and findings"
    why = "nothing was heard from its Build run for 9.2 hours before this server started"
    assert report["carried_on"] == {p.cid: why}, "the report names the silence it carried on after"
    again = await restart.resume_interrupted(app, p.catalog, booted=p.booted)
    assert again["resumed"] == [] and len(starts) == 1, "not lost, and not started twice"
    assert card == [], "nothing was handed in, approved or read by a second look"


@pytest.mark.asyncio
async def test_a_run_cut_minutes_before_the_stop_is_carried_on_however_long_ago_it_started(
    tmp_path: Path, card: list[str]
) -> None:
    p = _stopped_run(tmp_path, ago=5 * HOUR)  # refused before: it started more than 3 hours before the boot
    _heard(p, 2 / 60)
    _server_before(p, booted=6, alive=1 / 60)
    report = await _restart().resume_interrupted(_app(p.catalog, starts := []), p.catalog, booted=p.booted)

    assert report["resumed"] == [p.cid] and len(starts) == 1, report
    assert report["carried_on"][p.cid].endswith("for 2 minutes before this server started")
    assert card == []


@pytest.mark.asyncio
async def test_a_long_run_heard_within_the_window_is_found_though_its_file_is_old(
    tmp_path: Path, card: list[str]
) -> None:
    """Started 45 hours before the boot and written to for 20 of them: silent 25 hours, inside the 36."""
    p = _stopped_run(tmp_path, ago=45 * HOUR)
    _written(p, 45)
    _heard(p, 25)
    _server_before(p, booted=46, alive=24.9)
    report = await _restart().resume_interrupted(_app(p.catalog, starts := []), p.catalog, booted=p.booted)

    assert report["resumed"] == [p.cid] and len(starts) == 1, report
    assert "for 25.0 hours" in report["carried_on"][p.cid]
    assert card == []


@pytest.mark.asyncio
async def test_a_run_silent_for_37_hours_carries_on_once(tmp_path: Path) -> None:
    p = _stopped_run(tmp_path, ago=40 * HOUR)
    _heard(p, 37)
    _server_before(p, booted=41, alive=36.9)
    report = await _restart().resume_interrupted(_app(p.catalog, starts := []), p.catalog, booted=p.booted)

    assert report["resumed"] == [p.cid] and len(starts) == 1, report
    assert "for 37.0 hours" in report["carried_on"][p.cid]


@pytest.mark.asyncio
@pytest.mark.parametrize("dial, quiet, carried", [("balanced", 70, True), ("balanced", 80, False), ("max", 80, True)])
async def test_a_run_that_went_quiet_while_its_server_ran_is_not_called_a_restart(
    tmp_path: Path, dial: str, quiet: float, carried: bool
) -> None:
    """Review 2026-10-07: a run that hung at noon while the server ran on was carried on at the next boot as
    "resuming after a restart". A live run says something within two of its pass limits and 15 minutes (balanced:
    75 minutes; max: 135); quieter than that before its server's last sign of life, it did not stop with it."""
    p = _stopped_run(tmp_path, ago=12 * HOUR)
    settings = forge_code_projects.conversation_metadata(p.catalog, p.cid)["settings"]
    settings["requested"]["token_economy"] = dial
    forge_code_projects.update_conversation_settings(p.catalog, p.cid, settings)
    _heard(p, 10 + quiet / 60)
    _server_before(p, booted=13, alive=10)
    report = await _restart().resume_interrupted(_app(p.catalog, starts := []), p.catalog, booted=p.booted)

    assert (report["resumed"] == [p.cid]) is carried and len(starts) == int(carried), report
    if not carried:
        why = report["not_resumed"][p.cid]
        said = autopilot_silence.took(quiet * 60)
        assert said == "1.3 hours" and why.startswith(f"nothing was heard from its Build run for {said} before")
        assert "while that server was still running" in why and why.endswith("Send a message and Thomas carries on")


@pytest.mark.asyncio
async def test_the_first_start_with_no_record_of_the_server_before_carries_on(tmp_path: Path) -> None:
    """Without a prior life record, an unfinished Autopilot run still carries on once."""
    p = _stopped_run(tmp_path, ago=9.5 * HOUR)
    _heard(p, 9.2)
    report = await _restart().resume_interrupted(_app(p.catalog, starts := []), p.catalog, booted=p.booted)

    assert report["resumed"] == [p.cid] and len(starts) == 1, report


@pytest.mark.asyncio
async def test_a_run_the_server_before_was_still_carrying_on_is_carried_on(tmp_path: Path) -> None:
    """The server before found it stopped with the server before it, and stopped itself before starting it."""
    p = _stopped_run(tmp_path, ago=21 * HOUR)
    _heard(p, 20)
    _server_before(p, booted=9, alive=8.99, carrying=frozenset({p.cid}))
    report = await _restart().resume_interrupted(_app(p.catalog, starts := []), p.catalog, booted=p.booted)

    assert report["resumed"] == [p.cid] and len(starts) == 1, report


def test_a_server_reads_the_life_before_its_own(tmp_path: Path) -> None:
    """Once a server has written its own life, the one before it is still what a survey at its start reads."""
    earlier, mine = Life(100.0, 900.0, stopped=frozenset({"c1"})), Life(1000.0, 1300.0, carrying=frozenset({"c2"}))
    autopilot_silence.record_life(tmp_path, mine, earlier)

    assert autopilot_silence.previous_life(tmp_path, 1000.0) == earlier, "this server's own start: the one before"
    assert autopilot_silence.previous_life(tmp_path, 2000.0) == mine, "the next server's start: this one"
    assert autopilot_silence.previous_life(tmp_path / "elsewhere", 2000.0) is None, "no record: None"


def test_the_silence_is_the_later_of_the_start_and_the_transcript(tmp_path: Path) -> None:
    started = 1_000_000.0
    assert autopilot_silence.last_heard(tmp_path, "", started) == started, "no run id: its start"
    assert autopilot_silence.last_heard(tmp_path, "run-x", started) == started, "no transcript: its start"
    path = _transcript_path(tmp_path, "run-x")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    os.utime(path, (started + 600, started + 600))
    assert autopilot_silence.last_heard(tmp_path, "run-x", started) == started + 600
    os.utime(path, (started - 600, started - 600))
    assert autopilot_silence.last_heard(tmp_path, "run-x", started) == started, "an older file is not the run's"


@pytest.mark.asyncio
async def test_a_project_handed_in_while_it_waited_to_carry_on_is_left_to_its_card(tmp_path: Path) -> None:
    """Review 2026-10-07, R1: the pass found it, then its conversation was copied out for a hand-in before the run
    could start. The run is not started into the green that is being handed over."""
    p = _stopped_run(tmp_path, ago=1 * HOUR)
    restart, app = _restart(), _app(p.catalog, starts := [])
    found = restart.survey(p.catalog, p.booted)
    forge_code_store.write_conversation(p.catalog, forge_code_store.load_conversation(p.root, p.cid))

    await restart._attempt(app, p.catalog, found, {})

    assert starts == [] and restart.report()["not_resumed"][p.cid] == restart.HANDED_IN


def _app_that_refuses(starts: list[dict[str, Any]]) -> dict[Any, Any]:
    async def start(body: dict[str, Any], *, port: int) -> tuple[int, dict[str, Any]]:
        starts.append(body)
        return 500, {"ok": False, "error": "Build is not taking runs"}

    return {APP_PRAXIS_START_CODE_RUN: start, APP_LOCAL_PORT: 8898}


async def _whole_pass(app: dict[Any, Any], catalog: Path, cid: str) -> dict[str, Any]:
    """This server's own pass, from its start until it has said what it did with *cid*, then its stop."""
    restart = _restart()
    app[restart.APP_AUTOPILOT_RESTART_TASK] = asyncio.create_task(restart.restart_pass(app, catalog_root=catalog))
    for _ in range(500):
        if (
            cid in restart.report()["not_resumed"]
            or cid in restart.report()["resumed"]
            or cid in restart.report().get("pending_reasons", {})
        ):
            break
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.2)  # the pass records what it did, then only beats every HEARTBEAT_S
    stopping = time.time()
    await restart.stop_restart_pass(app)
    return {**restart.report(), "stopping": stopping}


@pytest.mark.asyncio
async def test_the_servers_own_pass_carries_the_09_29_stop_on(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The 09-29 shape through the pass the server itself starts: survey, start, and its own life recorded."""
    restart, p = _restart(), _stopped_run(tmp_path, ago=9.5 * HOUR)
    _written(p, 9.5)
    _heard(p, 9.2)
    _server_before(p, booted=14, alive=9.15)
    for name, value in (("SETTLE_S", 0.0), ("TICK_S", 0.0)):
        monkeypatch.setattr(restart, name, value)
    monkeypatch.setattr(restart._pass, "booted_at", p.booted)

    done = await _whole_pass(_app(p.catalog, starts := []), p.catalog, p.cid)

    assert done["resumed"] == [p.cid] and len(starts) == 1, done
    assert done["carried_on"][p.cid].endswith("for 9.2 hours before this server started")
    life = autopilot_silence.previous_life(p.catalog, p.booted + HOUR)
    assert life is not None and life.booted_at == p.booted and not life.stopped and not life.carrying, life


@pytest.mark.asyncio
async def test_a_run_a_restart_could_not_start_is_carried_on_at_the_next_boot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refused start stays pending and is recorded as carrying for the next boot."""
    restart = _restart()
    p = _stopped_run(tmp_path, ago=1 * HOUR)
    for name, value in (("SETTLE_S", 0.0), ("TICK_S", 0.0)):
        monkeypatch.setattr(restart, name, value)
    monkeypatch.setattr(restart._pass, "booted_at", p.booted)

    first = await _whole_pass(_app_that_refuses(refused := []), p.catalog, p.cid)

    assert refused and p.cid not in first["not_resumed"]
    assert p.cid in first["pending"] and first["pending_reasons"][p.cid] == restart.REFUSED
    life = autopilot_silence.previous_life(p.catalog, p.booted + 20 * HOUR)
    assert life is not None and life.booted_at == p.booted and life.carrying == {p.cid} and not life.stopped
    assert life.alive_at >= first["stopping"], "the stop is its last sign of life"
    monkeypatch.setattr(restart, "_pass", restart._Pass())
    later = await restart.resume_interrupted(_app(p.catalog, starts := []), p.catalog, booted=p.booted + 20 * HOUR)

    assert later["resumed"] == [p.cid] and len(starts) == 1, later
