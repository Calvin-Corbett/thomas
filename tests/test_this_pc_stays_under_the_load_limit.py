"""New work waits while this PC is over the load limit, and never forever (2026-10-25).

"make sure thomas doesnt ever max out the pc always 90%": the PC sat at 100% CPU with 15 to 26 threads waiting and
nothing finished for 17 hours. Fake readings stand in for psutil, and a fake clock for time.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from thomas.core import machine_capacity, machine_load
from thomas.core.machine_load import Reading
from thomas.server.precard import pool
from thomas.tools import check_run

BUSY, CALM = Reading(cpu=97.0, memory=50.0, samples=10), Reading(cpu=40.0, memory=50.0, samples=10)


@pytest.fixture(autouse=True)
def _limit_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(machine_load.LIMIT_ENV, "90")
    monkeypatch.delenv(machine_load.CAPPED_ENV, raising=False)  # a run started by the capped server inherits it


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _readings(*values: Reading) -> Any:
    queue = list(values)
    return lambda: queue.pop(0) if len(queue) > 1 else queue[0]


@pytest.mark.parametrize(
    ("now", "words"),
    [(BUSY, "CPU is at 97%"), (Reading(cpu=10.0, memory=93.0, samples=1), "memory is at 93%"), (CALM, "")],
)
def test_over_limit_names_what_is_full(now: Reading, words: str) -> None:
    said = machine_load.over_limit(now)
    assert (words in said) if words else said == ""


def test_under_the_hard_cpu_cap_only_memory_makes_work_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    """The caged server's job cap holds Thomas under the limit, so a CPU wait would only give way to other programs."""
    monkeypatch.setenv(machine_load.CAPPED_ENV, "90")
    assert machine_load.over_limit(BUSY) == ""
    assert "memory is at 93%" in machine_load.over_limit(Reading(cpu=99.0, memory=93.0, samples=1))


def test_a_pc_that_cannot_be_read_is_room_not_a_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(machine_load, "reading", lambda: None)
    assert machine_load.over_limit() == ""


def test_the_limit_comes_from_the_environment_and_zero_turns_it_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(machine_load.LIMIT_ENV, "75")
    assert machine_load.limit() == 75.0 and machine_load.over_limit(Reading(80.0, 10.0, 1))
    monkeypatch.setenv(machine_load.LIMIT_ENV, "0")
    assert machine_load.over_limit(BUSY) == ""
    monkeypatch.setenv(machine_load.LIMIT_ENV, "lots")
    assert machine_load.limit() == machine_load.DEFAULT_LIMIT


def test_under_pytest_the_limit_is_off_unless_a_test_turns_it_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(machine_load.LIMIT_ENV)
    assert machine_load.limit() == 0.0, "the suite must not wait on the machine that runs it"


def test_work_starts_at_once_when_there_is_room() -> None:
    clock = Clock()
    assert machine_load.wait_for_room(max_wait_s=600, read=lambda: CALM, sleep=clock.sleep, clock=clock) == (0.0, "")


def test_work_waits_until_the_pc_has_room() -> None:
    clock = Clock()
    waited, why = machine_load.wait_for_room(
        max_wait_s=600, read=_readings(BUSY, BUSY, CALM), sleep=clock.sleep, clock=clock
    )
    assert waited == 2 * machine_load.CHECK_S and "CPU is at 97%" in why


def test_a_wait_never_outlasts_its_limit_even_when_the_pc_stays_busy() -> None:
    clock = Clock()
    waited, why = machine_load.wait_for_room(max_wait_s=12, read=lambda: BUSY, sleep=clock.sleep, clock=clock)
    assert waited == 12 and why, "load from outside Thomas must not stop him for good"


def test_the_event_loop_wait_gives_way_too(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []

    async def no_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(machine_load.asyncio, "sleep", no_sleep)
    waited, why = asyncio.run(machine_load.await_room(max_wait_s=600, read=_readings(BUSY, CALM)))
    assert slept == [machine_load.CHECK_S] and "CPU" in why


def test_a_build_run_waits_only_while_another_is_going(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[float] = []

    async def await_room(*, max_wait_s: float, **_kw: Any) -> tuple[float, str]:
        calls.append(max_wait_s)
        return 0.0, ""

    monkeypatch.setattr(machine_capacity.machine_load, "await_room", await_room)
    asyncio.run(machine_capacity.await_room_for_run(False))
    assert calls == [], "with nothing running, waiting would only stop Thomas"
    asyncio.run(machine_capacity.await_room_for_run(True))
    assert calls == [machine_capacity.RUN_LOAD_WAIT_S]


@pytest.mark.parametrize(("check", "waits"), [("pytest", True), ("git_status", False)])
def test_a_teams_test_run_waits_for_room_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, check: str, waits: bool
) -> None:
    # Since 2026-11-13 the room it waits for is its turn in the one line of test runs (machine_load.Line): until then
    # it waited at most 120 s and started on a busy PC anyway (tests/test_test_runs_wait_in_one_line.py).
    asked: list[str] = []
    clock = [0.0]

    class Line:
        def join(self, label: str) -> int:
            asked.append(label)
            return 1

        def look(self, _ticket: int) -> tuple[bool, int]:
            clock[0] += 42.0
            return True, 0

        def leave(self, _ticket: int) -> None:
            pass

    monkeypatch.setattr(check_run.machine_load, "line", lambda: Line())
    monkeypatch.setattr(check_run, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(check_run, "_JOBS", {})
    monkeypatch.setattr(check_run, "build_argv", lambda *_a: ["x"])
    monkeypatch.setattr(check_run, "_run_blocking", lambda *_a: (0, "ok"))
    result = asyncio.run(check_run.CheckRunTool(tmp_path).execute({"check": check}))
    assert result.ok and asked == (["check.run"] if waits else [])
    assert ("waited 42 s for its turn" in result.data.get("waited_for_room", "")) is waits


def test_a_check_shard_waits_for_room_before_it_asks_for_a_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []
    monkeypatch.setattr(pool.machine_load, "wait_for_room", lambda **kw: order.append(f"room {kw['max_wait_s']}"))

    class Admitted:
        def __init__(self, *_a: Any, **_kw: Any) -> None:
            order.append("place")

        def __enter__(self) -> None:
            return None

        def __exit__(self, *_a: Any) -> None:
            return None

    monkeypatch.setattr(pool.capacity_ledger, "admitted", Admitted)
    monkeypatch.setattr(pool.capacity_ledger, "pool_size", lambda own: own)
    monkeypatch.setattr(pool.machine_capacity, "check_shard_mb", lambda *_a: 100)
    monkeypatch.setattr(pool.green_checkout, "green_root", lambda: tmp_path)
    monkeypatch.setattr(pool, "run_measured", lambda *_a, **_kw: (0, "ran", 0.0, 0.0))
    code, _out = pool.runner(None, files=1, record_peaks=False)(["x"], cwd=tmp_path, env={}, timeout_s=10)
    assert code == 0 and order == [f"room {pool.LOAD_WAIT_S}", "place"], order


class _Deadline:
    """A check's deadline whose time runs out as it is read: 1000 s, then 400 s after the wait for room."""

    def __init__(self) -> None:
        self.left = [1000.0, 400.0]
        self.passed = False

    def remaining(self) -> float:
        return self.left.pop(0) if len(self.left) > 1 else self.left[0]

    def words(self) -> str:
        return "out of time"


def test_a_shards_place_wait_is_what_the_wait_for_room_left(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    asked: dict[str, Any] = {}
    monkeypatch.setattr(pool.machine_load, "wait_for_room", lambda **kw: asked.update(room=kw["max_wait_s"]))

    class Admitted:
        def __init__(self, *_a: Any, **kw: Any) -> None:
            asked["place"] = kw["wait_s"]

        def __enter__(self) -> None:
            return None

        def __exit__(self, *_a: Any) -> None:
            return None

    monkeypatch.setattr(pool.capacity_ledger, "admitted", Admitted)
    monkeypatch.setattr(pool.capacity_ledger, "pool_size", lambda own: own)
    monkeypatch.setattr(pool.machine_capacity, "check_shard_mb", lambda *_a: 100)
    monkeypatch.setattr(pool.green_checkout, "green_root", lambda: tmp_path)
    monkeypatch.setattr(pool, "run_measured", lambda *_a, **_kw: (0, "ran", 0.0, 0.0))
    pool.runner(_Deadline(), files=1, record_peaks=False)(["x"], cwd=tmp_path, env={}, timeout_s=10)  # type: ignore[arg-type]
    assert asked == {"room": pool.LOAD_WAIT_S, "place": pytest.approx(400.1)}, "not the 1000 s it had before"
