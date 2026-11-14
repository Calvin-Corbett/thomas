"""Interrupted Autopilot work survives old transcripts, busy capacity, and refused starts."""

import asyncio
import os
from pathlib import Path
from typing import Any

import pytest

from tests.test_a_restart_does_not_stop_a_thomas_project import (
    _app,
    _handed_in,
    _stopped_by_you,
    _stopped_run,
)
from thomas.core import machine_capacity
from thomas.server import autopilot_restart as restart
from thomas.server import autopilot_silence, thomas_project
from thomas.server.praxis.launch import APP_PRAXIS_START_CODE_RUN
from thomas.server.routes.evolve_agent_runtime import _transcript_path

HOUR = 3600.0
DAY = 24 * HOUR


def _old(p: Any, *, days: float = 25) -> None:
    moment = p.booted - days * DAY
    path = thomas_project._live_file(p.root, p.cid)
    os.utime(path, (moment, moment))
    transcript = _transcript_path(p.catalog, "run-before")
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text('{"type":"assistant","text":"working"}\n', encoding="utf-8")
    os.utime(transcript, (moment, moment))


def _before(p: Any, *, booted: float, alive: float) -> None:
    autopilot_silence.record_life(p.catalog, autopilot_silence.Life(p.booted - booted, p.booted - alive), None)


@pytest.mark.asyncio
@pytest.mark.parametrize("recorded", [False, True])
async def test_a_25_day_old_run_carries_on_with_or_without_a_previous_life(tmp_path: Path, recorded: bool) -> None:
    p = _stopped_run(tmp_path, ago=25 * DAY)
    _old(p)
    if recorded:
        _before(p, booted=1 * HOUR, alive=0.5 * HOUR)
    result = await restart.resume_interrupted(_app(p.catalog, starts := []), p.catalog, booted=p.booted)
    assert result["resumed"] == [p.cid] and len(starts) == 1, result
    assert "600.0 hours" in result["carried_on"][p.cid]


@pytest.mark.asyncio
async def test_a_run_last_heard_before_the_previous_server_started_carries_on(tmp_path: Path) -> None:
    p = _stopped_run(tmp_path, ago=25 * DAY)
    _old(p)
    _before(p, booted=20 * DAY, alive=HOUR)
    result = await restart.resume_interrupted(_app(p.catalog, starts := []), p.catalog, booted=p.booted)
    assert result["resumed"] == [p.cid] and len(starts) == 1, result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,autonomy,reason",
    [("stopped", 5, restart.YOU_STOPPED), ("handed_in", 5, restart.HANDED_IN), ("running", 1, restart.NOT_AUTOPILOT)],
)
async def test_old_work_still_respects_explicit_ends_and_autonomy(
    tmp_path: Path, kind: str, autonomy: int, reason: str
) -> None:
    p = _stopped_run(tmp_path, ago=25 * DAY, autonomy=autonomy)
    app = _app(p.catalog, starts := [])
    if kind == "stopped":
        _stopped_by_you(p, app)
    elif kind == "handed_in":
        _handed_in(p, app)
    _old(p)
    result = await restart.resume_interrupted(app, p.catalog, booted=p.booted)
    assert starts == [] and result["resumed"] == [], result
    assert result["not_resumed"][p.cid] == reason


@pytest.mark.asyncio
async def test_capacity_waits_past_limit_without_spending_a_try(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    p = _stopped_run(tmp_path)
    clock = [p.booted]
    checks = [0]
    allow = asyncio.Event()

    def refusal(active: int) -> str | None:
        checks[0] += 1
        return None if allow.is_set() else "busy"

    async def sleep(_seconds: float) -> None:
        clock[0] += restart.WAIT_LIMIT_S + 1
        await asyncio.sleep(0.001)

    monkeypatch.setattr(restart, "_clock", lambda: clock[0])
    monkeypatch.setattr(restart, "_sleep", sleep)
    monkeypatch.setattr(restart, "_cage_down", lambda: False)
    monkeypatch.setattr(machine_capacity, "admission_refusal", refusal)
    monkeypatch.setattr(restart, "_pass", restart._Pass(booted_at=p.booted))
    app = _app(p.catalog, starts := [])
    task = asyncio.create_task(restart.restart_pass(app, catalog_root=p.catalog))
    try:
        for _ in range(100):
            if checks[0] > 2:
                break
            await asyncio.sleep(0.01)
        assert checks[0] > 2 and starts == [] and restart.report()["pending"] == [p.cid]
        assert restart.report()["not_resumed"] == {}
        life = autopilot_silence.previous_life(p.catalog, clock[0] + 1)
        assert life is not None and p.cid in life.carrying
        allow.set()
        for _ in range(100):
            if starts:
                break
            await asyncio.sleep(0.01)
        assert len(starts) == 1 and restart.report()["resumed"] == [p.cid]
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_three_runs_check_capacity_before_each_serial_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil

    from thomas.forge.anvil import forge_code_projects

    p = _stopped_run(tmp_path)
    for index in (2, 3):
        cid = f"{p.cid}-{index}"
        shutil.copyfile(thomas_project._live_file(p.root, p.cid), thomas_project._live_file(p.root, cid))
        settings = forge_code_projects.conversation_metadata(p.catalog, p.cid)["settings"]
        forge_code_projects.bind_conversation(p.catalog, cid, p.root, settings=settings, allow_without_history=True)
    checks: list[int] = []
    active = [0]
    original = _app(p.catalog, starts := [])[APP_PRAXIS_START_CODE_RUN]

    def refusal(count: int) -> None:
        checks.append(count)
        assert active[0] == 0, "a second run started before the previous one finished"
        return None

    async def start(body: dict[str, Any], *, port: int) -> tuple[int, dict[str, Any]]:
        active[0] += 1
        try:
            await asyncio.sleep(0)
            return await original(body, port=port)
        finally:
            active[0] -= 1

    monkeypatch.setattr(machine_capacity, "admission_refusal", refusal)
    app = _app(p.catalog, starts)
    app[APP_PRAXIS_START_CODE_RUN] = start
    result = await restart.resume_interrupted(app, p.catalog, booted=p.booted)
    assert len(result["resumed"]) == len(starts) == 3 and len(checks) >= 3, result


@pytest.mark.asyncio
async def test_refused_starts_are_carried_in_life_and_next_server_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    p = _stopped_run(tmp_path)
    monkeypatch.setattr(machine_capacity, "admission_refusal", lambda active: None)
    monkeypatch.setattr(restart, "_pass", restart._Pass(booted_at=p.booted))
    app = _app(p.catalog, [])
    attempts: list[dict[str, Any]] = []

    async def refuse(body: dict[str, Any], *, port: int) -> tuple[int, dict[str, Any]]:
        attempts.append(body)
        return 500, {"ok": False}

    app[APP_PRAXIS_START_CODE_RUN] = refuse
    found = restart.survey(p.catalog, p.booted)
    tries: dict[str, int] = {}
    for _ in range(5):
        await restart._attempt(app, p.catalog, found, tries)
    restart._save_life(p.catalog)
    assert len(attempts) == 5 and len(found) == 1
    assert restart.report()["pending"] == [p.cid]
    assert restart.report()["pending_reasons"][p.cid] == restart.REFUSED
    assert restart.phase(thomas_project._read_live(p.root, p.catalog, p.cid)) == ("waiting", restart.REFUSED)
    life = autopilot_silence.previous_life(p.catalog, p.booted + HOUR)
    assert life is not None and p.cid in life.carrying and p.cid not in life.stopped
    monkeypatch.setattr(restart, "_pass", restart._Pass())
    result = await restart.resume_interrupted(_app(p.catalog, starts := []), p.catalog, booted=p.booted + HOUR)
    assert result["resumed"] == [p.cid] and len(starts) == 1, result


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["unreadable", "exception"])
async def test_pre_start_failures_keep_retrying_and_remain_eligible_next_boot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    p = _stopped_run(tmp_path)
    monkeypatch.setattr(machine_capacity, "admission_refusal", lambda active: None)
    monkeypatch.setattr(restart, "_pass", restart._Pass(booted_at=p.booted))
    found = restart.survey(p.catalog, p.booted)
    app = _app(p.catalog, starts := [])
    original_read = thomas_project._read_live
    if failure == "unreadable":
        monkeypatch.setattr(thomas_project, "_read_live", lambda *args: None)
    else:

        def broken(*args: Any) -> None:
            raise OSError("temporary read failure")

        monkeypatch.setattr(thomas_project, "_read_live", broken)
    tries: dict[str, int] = {}
    pre_start_failures: dict[str, int] = {}
    for _ in range(5):
        await restart._attempt(app, p.catalog, found, tries, pre_start_failures)
    monkeypatch.setattr(thomas_project, "_read_live", original_read)
    assert tries == {} and starts == [] and len(found) == 1
    assert restart.report()["pending"] == [p.cid]
    assert restart.report()["pending_reasons"][p.cid] == restart.COULD_NOT_START
    assert restart.phase(original_read(p.root, p.catalog, p.cid)) == ("waiting", restart.COULD_NOT_START)
    restart._save_life(p.catalog)
    life = autopilot_silence.previous_life(p.catalog, p.booted + HOUR)
    assert life is not None and p.cid in life.carrying and p.cid not in life.stopped
    monkeypatch.setattr(restart, "_pass", restart._Pass())
    result = await restart.resume_interrupted(_app(p.catalog, starts), p.catalog, booted=p.booted + HOUR)
    assert result["resumed"] == [p.cid] and len(starts) == 1


@pytest.mark.parametrize("reason", [restart.NOT_READY, restart.CAGE_DOWN])
def test_server_unavailable_shows_why_even_when_carried_to_next_boot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reason: str
) -> None:
    p = _stopped_run(tmp_path)
    monkeypatch.setattr(restart, "_pass", restart._Pass(booted_at=p.booted))
    conversation = thomas_project._read_live(p.root, p.catalog, p.cid)
    assert conversation is not None
    restart._pass.carrying[p.cid] = reason
    assert restart.phase(conversation) == ("ended", reason)
    assert thomas_project.project_phase(p.root, p.catalog, p.cid) == ("ended", reason)
    restart._pass.catalog = p.catalog
    restart._save_life(p.catalog)
    life = autopilot_silence.previous_life(p.catalog, p.booted + HOUR)
    assert life is not None and p.cid in life.carrying and p.cid not in life.stopped
