"""The restart survey no longer competes with the server's own start.

It parses every conversation record in pure Python on a thread, about 2.5 s of CPU on a long history, and it started
during ``runner.setup()`` before the port was even open, so the start and then the first page load shared the
interpreter with it. It now waits until the server says it is listening. A caller that never says so (a test, a
script) is surveyed at once, as before.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from thomas.server import autopilot_restart as restart


@pytest.fixture
def surveyed(monkeypatch: pytest.MonkeyPatch) -> asyncio.Event:
    done = asyncio.Event()

    def fake_survey(_catalog, _booted):
        done.set()
        return []

    monkeypatch.setattr(restart, "survey", fake_survey)
    monkeypatch.setattr(restart, "_save_life", lambda _catalog: None)
    monkeypatch.setattr(restart, "LISTEN_GRACE_S", 0.0)
    return done


async def _stop(task: asyncio.Task) -> None:
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_the_survey_does_not_start_until_the_server_listens(surveyed: asyncio.Event, tmp_path: Path) -> None:
    listening = asyncio.Event()
    task = asyncio.create_task(restart.restart_pass({restart.APP_SERVER_LISTENING: listening}, catalog_root=tmp_path))
    try:
        await asyncio.sleep(0.3)
        assert not surveyed.is_set(), "the survey ran while the server was still starting"
        listening.set()
        await asyncio.wait_for(surveyed.wait(), 5)
    finally:
        await _stop(task)


@pytest.mark.asyncio
async def test_a_caller_with_no_listening_signal_is_surveyed_at_once(surveyed: asyncio.Event, tmp_path: Path) -> None:
    task = asyncio.create_task(restart.restart_pass({}, catalog_root=tmp_path))
    try:
        await asyncio.wait_for(surveyed.wait(), 5)
    finally:
        await _stop(task)


@pytest.mark.asyncio
async def test_a_server_that_never_opens_its_port_is_still_surveyed(
    surveyed: asyncio.Event, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(restart, "LISTEN_WAIT_S", 0.2)
    task = asyncio.create_task(
        restart.restart_pass({restart.APP_SERVER_LISTENING: asyncio.Event()}, catalog_root=tmp_path)
    )
    try:
        await asyncio.wait_for(surveyed.wait(), 5)
    finally:
        await _stop(task)


@pytest.mark.asyncio
async def test_starting_the_pass_gives_the_app_a_listening_signal(
    surveyed: asyncio.Event, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(restart.autopilot_park, "loop_enabled", lambda: True)
    app: dict = {}
    restart.start_restart_pass(app)
    try:
        assert isinstance(app[restart.APP_SERVER_LISTENING], asyncio.Event)
        assert not app[restart.APP_SERVER_LISTENING].is_set()
    finally:
        await _stop(app[restart.APP_AUTOPILOT_RESTART_TASK])
