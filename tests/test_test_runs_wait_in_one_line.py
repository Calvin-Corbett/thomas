"""Test runs wait their turn in one line for the whole PC (machine_load.Line).

On 2026-11-13 ten Builds ran thirteen test runs at once on a PC already at 90%. The step log of that morning:
48 check.run calls ended at the 9-minute limit (7.2 hours of them, nothing learned), a check before a card ran 92
minutes and ended "unavailable" because its shards timed out, and no change landed. A test run waited at most 120 s
for room and then started anyway, and under the caged server's CPU cap it did not wait at all. How check.run
uses the line is in tests/test_check_run_waits_in_the_line.py.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from thomas.core import machine_load

CALM = machine_load.Reading(20.0, 30.0, 5)
BUSY = machine_load.Reading(97.0, 30.0, 5)
OTHER = 4242  # another Build's process


def _world() -> SimpleNamespace:
    return SimpleNamespace(now=1000.0, reading=CALM, dead=set(), held=None)


def _line(tmp_path: Path, world: SimpleNamespace, *, cpus: int = 16) -> machine_load.Line:
    def born(pid: int) -> float | None:
        return None if pid in world.dead else (5.0 if pid == os.getpid() else 7.0)

    return machine_load.Line(
        tmp_path / "line.sqlite3",
        cpus=cpus,
        cap=lambda: 90.0,
        read=lambda: world.reading,
        clock=lambda: world.now,
        born=born,
        held=lambda: world.held,
    )


def _others(line: machine_load.Line, world: SimpleNamespace, *, running: int = 0, waiting: int = 0) -> None:
    """Tickets of another Build's process, written the way that process would have."""
    with sqlite3.connect(line.path) as db:
        for started in [world.now] * running + [None] * waiting:
            db.execute(
                "INSERT INTO line (pid, born, label, joined, seen, started) VALUES (?, 7.0, 'check.run', ?, ?, ?)",
                (OTHER, world.now, world.now, started),
            )


def test_a_calm_pc_starts_only_the_runs_it_has_room_for(tmp_path: Path) -> None:
    world = _world()
    line = _line(tmp_path, world)
    assert line.places() == (14, 2), "90% of 16 threads at most; two may always run"
    tickets = [line.join("check.run") for _ in range(20)]
    started = [ticket for ticket in tickets if line.look(ticket)[0]]
    # 20% busy and each new run counted as one thread (6.25%): the eleventh would be the last under 90%.
    assert started == tickets[:11], "runs that just started are counted before the average shows them"
    world.now += machine_load.WINDOW_S + 1  # the average has caught up, and still says calm
    started = [ticket for ticket in tickets if line.look(ticket)[0]]
    assert started == tickets[:14], "never more at once than the limit leaves threads for"


def test_a_pc_at_its_limit_starts_only_the_least_and_the_rest_wait_in_order(tmp_path: Path) -> None:
    world = _world()
    world.reading = BUSY
    line = _line(tmp_path, world)
    first, second, third, fourth = (line.join("check.run") for _ in range(4))
    assert [line.look(t) for t in (first, second, third, fourth)] == [(True, 0), (True, 0), (False, 0), (False, 1)]
    line.leave(first)
    assert line.look(fourth) == (False, 1), "a later run never starts ahead of an earlier one"
    assert line.look(third) == (True, 0)
    assert line.look(fourth) == (False, 0)


def test_a_place_whose_process_died_is_given_up(tmp_path: Path) -> None:
    world = _world()
    world.reading = BUSY
    line = _line(tmp_path, world)
    _others(line, world, running=2)
    mine = line.join("check.run")
    assert line.look(mine) == (False, 0), "both places that may always run are taken"
    world.dead.add(OTHER)
    assert line.look(mine) == (True, 0)
    assert [row["pid"] for row in line.rows()] == [os.getpid()], "the dead process's tickets are gone"


def test_a_place_held_longer_than_any_test_run_is_given_up(tmp_path: Path) -> None:
    world = _world()
    world.reading = BUSY
    line = _line(tmp_path, world)
    _others(line, world, running=2)
    mine = line.join("check.run")
    assert line.look(mine) == (False, 0)
    world.now += machine_load.LINE_RUN_MAX_S + 1
    assert line.look(mine) == (True, 0), "a place nobody gave back does not hold the line for good"


def test_a_waiting_run_that_stopped_asking_does_not_hold_the_line(tmp_path: Path) -> None:
    world = _world()
    world.reading = BUSY
    line = _line(tmp_path, world)
    _others(line, world, running=1, waiting=1)
    mine = line.join("check.run")
    assert line.look(mine) == (False, 1), "the one free place belongs to the run that came first"
    world.now += machine_load.LINE_GONE_S + 1  # that run never asked again
    assert line.look(mine) == (True, 0)


def test_a_ticket_given_up_while_its_process_could_not_ask_takes_its_old_place_again(tmp_path: Path) -> None:
    world = _world()
    world.reading = BUSY
    line = _line(tmp_path, world)
    _others(line, world, running=2)
    early, late = line.join("check.run"), line.join("check.run")
    with sqlite3.connect(line.path) as db:  # another process took it for gone while this one slept
        db.execute("DELETE FROM line WHERE ticket=?", (early,))
    assert line.look(late) == (False, 0)
    assert line.look(early) == (False, 0), "it is back, and ahead of the run that came after it"
    assert line.look(late) == (False, 1)


def test_there_is_no_line_under_the_test_suite_or_with_the_limit_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(machine_load, "_line", None)
    monkeypatch.delenv(machine_load.LIMIT_ENV, raising=False)
    assert machine_load.line() is None, "the suite's own test runs never wait on each other"
    monkeypatch.setenv(machine_load.LIMIT_ENV, "0")
    assert machine_load.line() is None
    monkeypatch.setenv(machine_load.LIMIT_ENV, "90")
    made = machine_load.line()
    assert made is not None and made is machine_load.line(), "one line for the process"
    assert made.path.name == machine_load.LINE_FILE


def test_a_place_goes_to_the_run_that_came_first_whichever_run_asks_first(tmp_path: Path) -> None:
    """Room for one more run was offered to whichever waiting run asked first, not to the first in line."""
    world = _world()
    world.reading = machine_load.Reading(80.0, 30.0, 5)  # room for one more run under 90%, not for two
    line = _line(tmp_path, world)
    _others(line, world, running=2)
    world.now += machine_load.WINDOW_S + 1  # those two are in the average by now
    waiting = [line.join("check.run") for _ in range(5)]
    assert line.look(waiting[-1]) == (False, 4), "the last to come is not offered the one free place"
    assert line.look(waiting[0]) == (True, 0)
    assert line.look(waiting[1]) == (False, 0), "and the run that just started is counted before the average shows it"


def test_under_the_cage_cpu_cap_room_is_what_the_cage_has_left_not_what_the_pc_reads(tmp_path: Path) -> None:
    """The cap holds the reading of the PC under the limit while the tree Thomas runs has nothing left to give."""
    world = _world()  # the PC reads 20%: by that alone eleven runs would start
    world.held = (30.0, 30.0)  # the cage may use 30% of the PC and is using all of it
    line = _line(tmp_path, world)
    tickets = [line.join("check.run") for _ in range(8)]
    assert [t for t in tickets if line.look(t)[0]] == tickets[:2], "only the two that may always run"
    world.held = (60.0, 35.0)  # the cap gave some back: 25% of 16 threads is room for four runs
    world.now += machine_load.WINDOW_S + 1
    assert [t for t in tickets if line.look(t)[0]] == tickets[:6]
    assert line.look(tickets[6]) == (False, 0)


def test_the_meter_reads_the_share_and_the_use_of_the_capped_job_it_is_in() -> None:
    clock, said = [0.0], [(60.0, 0)]
    meter = machine_load.JobMeter(lambda: said[0], clock=lambda: clock[0], cpus=10)
    assert meter.read() == (60.0, 60.0), "nothing measured yet: as if the tree used all it may"
    clock[0], said[0] = 10.0, (60.0, int(10 * 1e7 * 10 * 0.415))  # 41.5% of ten threads for ten seconds
    assert meter.read() == (60.0, pytest.approx(41.5))
    said[0] = None  # in no capped job
    assert meter.read() is None


def test_a_process_under_no_cap_reads_no_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(machine_load.CAPPED_ENV, raising=False)
    assert machine_load.JobMeter().read() is None, "your own server's Builds are not held by the cage's cap"


def test_ages_in_the_line_are_read_from_the_monotonic_clock() -> None:
    """Setting the wall clock forward gave up every running place and wiped the order of the waiting runs."""
    import inspect
    import time

    assert inspect.signature(machine_load.Line).parameters["clock"].default is time.monotonic
