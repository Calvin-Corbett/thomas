"""A sweep stopped partway through a long tick leaves no second sweep behind when it is started again.

``thomas.core.aliveness`` used to wait two seconds for the thread, forget it, and clear the one flag the thread was
watching when the next start came. A tick that ran longer than that went on beside the new thread, two sweeps on one world
and one log. ``thomas.core.engine_manager`` lists the sweep for the tools panel and starts it for the command line, and
those are held here too, with ``thomas.server.aliveness_default``, which starts the server's engines without it.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from tests._aliveness_fakes import isolated_gate, obs
from thomas.core import aliveness
from thomas.core.aliveness import AlivenessLoop
from thomas.core.aliveness_drives import Drives
from thomas.core.aliveness_log import MuteLog
from thomas.core.aliveness_world import Observation, WorldModel

ROOT = Path(__file__).resolve().parents[1]


class SlowSensor:
    """The first look waits to be let go, and every look counts how many are under way at once."""

    name = "slow"

    def __init__(self) -> None:
        self.let_go = threading.Event()
        self.first_started = threading.Event()
        self.looks = 0
        self.under_way = 0
        self.most_at_once = 0
        self._lock = threading.Lock()

    def sample(self) -> list[Observation]:
        with self._lock:
            self.looks += 1
            self.under_way += 1
            self.most_at_once = max(self.most_at_once, self.under_way)
            first = self.looks == 1
        try:
            if first:
                self.first_started.set()
                self.let_go.wait(10)
            return [obs("branch", "dev")]
        finally:
            with self._lock:
                self.under_way -= 1


def _loop(tmp_path: Path, sensor: SlowSensor) -> AlivenessLoop:
    return AlivenessLoop(
        world=WorldModel([sensor]),
        drives=Drives(),
        mute_log=MuteLog(tmp_path / "mute.jsonl"),
        gate=isolated_gate(tmp_path),
    )


def _wait_for(condition: Callable[[], bool], seconds: float = 5.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.01)
    return False


def test_a_start_after_a_stop_that_gave_up_waits_for_the_old_tick(tmp_path: Path) -> None:
    sensor = SlowSensor()
    loop = _loop(tmp_path, sensor)
    loop.start(interval_s=0.02)
    assert sensor.first_started.wait(5)
    old = loop._thread

    loop.stop(timeout=0.05)  # gives up: the tick is still inside the sensor
    assert old is not None and old.is_alive()
    assert loop.running is False  # it was told to stop

    loop.start(interval_s=0.02)
    assert loop.running is True
    time.sleep(0.2)
    assert sensor.looks == 1, "the new thread looked while the old tick was still under way"

    sensor.let_go.set()
    try:
        assert _wait_for(lambda: sensor.looks >= 3), "the new sweep never ran"
        assert not old.is_alive(), "the stopped thread went on sweeping"
        assert sensor.most_at_once == 1
    finally:
        loop.stop()


def test_a_stop_with_no_limit_waits_for_the_tick_and_forgets_the_thread(tmp_path: Path) -> None:
    sensor = SlowSensor()
    loop = _loop(tmp_path, sensor)
    loop.start(interval_s=0.02)
    assert sensor.first_started.wait(5)
    threading.Timer(0.3, sensor.let_go.set).start()

    began = time.monotonic()
    loop.stop(timeout=None)

    assert time.monotonic() - began >= 0.25
    assert loop._thread is None
    assert loop.running is False


def test_a_stop_that_gave_up_keeps_the_thread_so_the_next_start_can_find_it(tmp_path: Path) -> None:
    sensor = SlowSensor()
    loop = _loop(tmp_path, sensor)
    loop.start(interval_s=0.02)
    assert sensor.first_started.wait(5)
    loop.stop(timeout=0.05)
    assert loop._thread is not None
    sensor.let_go.set()
    loop.stop()
    assert loop._thread is None


def test_retiring_the_loop_waits_and_forgets_it_and_builds_nothing_when_there_is_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(aliveness, "_loop", None)
    aliveness.retire_aliveness_loop()
    assert aliveness._loop is None, "retiring built a loop, which writes the permission file"

    sensor = SlowSensor()
    sensor.let_go.set()
    loop = _loop(tmp_path, sensor)
    monkeypatch.setattr(aliveness, "_loop", loop)
    loop.start(interval_s=0.02)
    assert _wait_for(lambda: sensor.looks >= 1)

    aliveness.retire_aliveness_loop()

    assert aliveness._loop is None
    assert loop.running is False
    assert loop._thread is None


def test_retiring_leaves_a_loop_that_was_started_again_while_it_waited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sensor = SlowSensor()
    loop = _loop(tmp_path, sensor)
    monkeypatch.setattr(aliveness, "_loop", loop)
    loop.start(interval_s=0.02)
    assert sensor.first_started.wait(5)

    retiring = threading.Thread(target=aliveness.retire_aliveness_loop)
    retiring.start()
    assert _wait_for(lambda: not loop.running)  # it was told to stop, and is still inside the tick
    loop.start(interval_s=0.02)  # started again before the retiring thread got its answer
    sensor.let_go.set()
    retiring.join(10)
    try:
        assert not retiring.is_alive()
        assert aliveness._loop is loop
        assert loop.running is True
    finally:
        loop.stop()


def test_the_engine_manager_that_leaves_the_sweep_to_its_plugin_lists_it_and_starts_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from thomas.core.engine_manager import EngineManager

    monkeypatch.setenv("THOMAS_ALIVENESS_ENABLED", "1")
    monkeypatch.setattr(aliveness, "_loop", None)
    manager = EngineManager()

    assert manager._leave_aliveness_to_its_plugin() is True

    listed = manager.status()["engines"]["aliveness"]
    assert (listed["running"], listed["error"]) == (False, None)
    assert aliveness._loop is None


def test_the_engine_list_reads_the_loop_as_it_is_now(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from thomas.core.engine_manager import EngineManager

    sensor = SlowSensor()
    sensor.let_go.set()
    loop = _loop(tmp_path, sensor)
    monkeypatch.setattr(aliveness, "_loop", loop)
    manager = EngineManager()
    manager._leave_aliveness_to_its_plugin()

    assert manager.status()["engines"]["aliveness"]["running"] is False
    loop.start(interval_s=0.02)
    try:
        assert _wait_for(lambda: manager.status()["engines"]["aliveness"]["running"] is True)
    finally:
        loop.stop()
    assert manager.status()["engines"]["aliveness"]["running"] is False


def test_the_command_line_still_starts_the_sweep_when_the_setting_asks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The server passes ``aliveness=False``. The command line passes nothing and keeps what it always had."""
    from thomas.core.engine_manager import EngineManager

    monkeypatch.setenv("THOMAS_ALIVENESS_ENABLED", "1")
    sensor = SlowSensor()
    sensor.let_go.set()
    loop = _loop(tmp_path, sensor)
    monkeypatch.setattr(aliveness, "_loop", loop)
    manager = EngineManager()

    assert manager._start_aliveness() is True
    try:
        assert loop.running is True
        assert manager.status()["engines"]["aliveness"]["running"] is True
    finally:
        loop.stop()


def test_the_setting_is_read_the_same_way_with_and_without_the_loop_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    from thomas.core.aliveness_setting import is_enabled

    for value in ("1", "true", "YES", " on ", "0", "", "no", "off", "2"):
        monkeypatch.setenv("THOMAS_ALIVENESS_ENABLED", value)
        assert is_enabled() is aliveness.is_enabled()
    monkeypatch.delenv("THOMAS_ALIVENESS_ENABLED")
    assert is_enabled() is False


def test_the_server_starts_its_engines_without_the_sweep_in_one_place() -> None:
    text = (ROOT / "thomas" / "server" / "aliveness_default.py").read_text(encoding="utf-8")
    assert "start_all(aliveness=False)" in text
    others = [
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "thomas" / "server").rglob("*.py")
        if ".start_all(" in path.read_text(encoding="utf-8")
    ]
    assert others == ["thomas/server/aliveness_default.py"]


def test_retiring_keeps_waiting_past_the_two_seconds_a_plain_stop_gives_a_look(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sensor = SlowSensor()
    loop = _loop(tmp_path, sensor)
    monkeypatch.setattr(aliveness, "_loop", loop)
    loop.start(interval_s=0.02)
    assert sensor.first_started.wait(5)

    retiring = threading.Thread(target=aliveness.retire_aliveness_loop)
    retiring.start()
    try:
        retiring.join(2.6)  # a stop that gave up at 2 s would have returned and forgotten the loop by now
        assert retiring.is_alive(), "retiring gave up while the look was still under way"
        assert aliveness._loop is loop, "the loop was forgotten with its look still running"
        assert loop._thread is not None and loop._thread.is_alive()
    finally:
        sensor.let_go.set()
        retiring.join(10)
    assert not retiring.is_alive()
    assert aliveness._loop is None
    assert loop._thread is None
