"""check.run puts a team's tests in the one line of test runs, and a call for them is never cut off or started twice.

The line itself, and the morning of 2026-11-13 that it answers, are in tests/test_test_runs_wait_in_one_line.py.
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from thomas.tools import check_run
from thomas.tools.check_run import CheckRunTool


class _FakeLine:
    """A line that lets a run start once ``open`` is set."""

    def __init__(self, *, open_: bool = True, ahead: int = 3) -> None:
        self.open, self.ahead = open_, ahead
        self.joined: list[str] = []
        self.gave_back: list[int] = []

    def join(self, label: str) -> int:
        self.joined.append(label)
        return len(self.joined)

    def look(self, ticket: int) -> tuple[bool, int]:
        return (True, 0) if self.open else (False, self.ahead)

    def leave(self, ticket: int) -> None:
        self.gave_back.append(ticket)


@pytest.fixture
def tool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """check.run with the line, the project's state and the test process stood in for."""
    world = SimpleNamespace(line=_FakeLine(), state="as-it-was", ran=[], timeouts=[])

    def run(argv: list[str], cwd: Path, timeout: float, started: dict[str, Any]) -> tuple[int | None, str]:
        world.ran.append(list(argv))
        world.timeouts.append(timeout)
        return 0, "1 passed"

    monkeypatch.setattr(check_run, "_JOBS", {})
    monkeypatch.setattr(check_run, "LINE_POLL_S", 0.01)
    monkeypatch.setattr(check_run, "_run_blocking", run)
    monkeypatch.setattr(check_run, "build_argv", lambda check, args, _root: [check, *args])
    monkeypatch.setattr(check_run.machine_load, "line", lambda: world.line)
    monkeypatch.setattr(check_run.check_reuse, "fingerprint", lambda *_a: world.state)
    monkeypatch.setattr(check_run.check_reuse, "recall", lambda *_a: None)
    monkeypatch.setattr(check_run.check_reuse, "remember", lambda *_a: None)
    yield CheckRunTool(tmp_path, reuse_dir=tmp_path / "reuse"), world
    check_run.forget_jobs()  # a run a test left waiting must not go on into the next test


TESTS = {"check": "pytest", "args": ["tests/test_x.py"]}


def test_a_teams_tests_take_a_place_and_give_it_back(tool) -> None:
    check, world = tool
    result = asyncio.run(check.execute(TESTS))
    assert result.ok and result.data["exit_code"] == 0
    assert world.line.joined == ["check.run"] and world.line.gave_back == [1]
    assert world.timeouts == [check_run.DEFAULT_TIMEOUT_S], "the wait takes nothing from the run's own time"


def test_a_check_that_is_not_pytest_takes_no_place(tool) -> None:
    check, world = tool
    result = asyncio.run(check.execute({"check": "git_status"}))
    assert result.ok and world.line.joined == [] and len(world.ran) == 1


def _until(done, seconds: float = 10.0) -> None:
    for _ in range(int(seconds / 0.01)):
        if done():
            return
        time.sleep(0.01)
    raise AssertionError("it did not happen in time")


def _held_run(check, monkeypatch: pytest.MonkeyPatch) -> threading.Event:
    """Make the test process of *check* go on until the returned event is set."""
    hold, real = threading.Event(), check._run

    async def slow(*args: Any) -> Any:
        while not hold.is_set():
            await asyncio.sleep(0.01)
        return await real(*args)

    monkeypatch.setattr(check, "_run", slow)
    return hold


def test_a_waiting_run_keeps_its_place_from_one_pass_of_a_build_to_the_next(
    tool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each pass of a Build is its own asyncio.run. A run on the loop of the pass gave its place back at every pass
    end and joined again at the back of the line (review, 2026-11-13)."""
    check, world = tool
    world.line = _FakeLine(open_=False, ahead=3)
    monkeypatch.setattr(check_run, "ANSWER_WITHIN_S", 0.05)
    first = asyncio.run(check.execute(TESTS))
    again = asyncio.run(check.execute(TESTS))  # the next pass makes the same call
    for waiting in (first, again):
        assert waiting.ok and waiting.data["status"] == "queued" and waiting.data["ahead"] == 3
        assert waiting.data["passed"] is None and "neither a pass nor a failure" in waiting.data["message"]
    assert world.line.joined == ["check.run"] and world.line.gave_back == [], "one place, kept"
    world.line.open = True
    monkeypatch.setattr(check_run, "ANSWER_WITHIN_S", 30.0)
    last = asyncio.run(check.execute(TESTS))
    assert last.ok and last.data["exit_code"] == 0 and last.data["passed"] is True
    assert len(world.ran) == 1 and world.line.joined == ["check.run"], "three calls, one place, one run"
    assert world.line.gave_back == [1]


def test_two_calls_for_the_same_tests_at_once_share_one_run(tool) -> None:
    check, world = tool

    async def scenario() -> list[Any]:
        return await asyncio.gather(check.execute(TESTS), check.execute(TESTS))

    one, two = asyncio.run(scenario())
    assert one.ok and two.ok and one.data["exit_code"] == two.data["exit_code"] == 0
    assert len(world.ran) == 1


def test_tests_that_waited_through_an_edit_run_once_on_the_project_as_it_is(
    tool, monkeypatch: pytest.MonkeyPatch
) -> None:
    check, world = tool
    world.line = _FakeLine(open_=False)
    monkeypatch.setattr(check_run, "ANSWER_WITHIN_S", 0.05)
    remembered: list[Any] = []
    monkeypatch.setattr(check_run.check_reuse, "remember", lambda _d, _r, _k, state, _data: remembered.append(state))
    first = asyncio.run(check.execute(TESTS))
    world.state = "after-an-edit"  # the team edited a file while its tests waited
    world.line.open = True
    monkeypatch.setattr(check_run, "ANSWER_WITHIN_S", 30.0)
    second = asyncio.run(check.execute(TESTS))
    assert first.data["status"] == "queued" and second.ok and second.data["exit_code"] == 0
    assert len(world.ran) == 1 and world.line.joined == ["check.run"], "the waiting run is the one that ran"
    assert remembered == ["after-an-edit"], "its verdict is kept for the project as it was when it ran"


def test_a_run_that_started_before_an_edit_is_ended_and_the_edited_project_gets_its_own(
    tool, monkeypatch: pytest.MonkeyPatch
) -> None:
    check, world = tool
    hold = _held_run(check, monkeypatch)
    monkeypatch.setattr(check_run, "ANSWER_WITHIN_S", 0.2)
    assert asyncio.run(check.execute(TESTS)).data["status"] == "running"
    world.state = "after-an-edit"
    assert asyncio.run(check.execute(TESTS)).data["status"] == "running"
    _until(lambda: world.line.gave_back == [1])  # the run for the old files ended and gave its place back
    hold.set()
    monkeypatch.setattr(check_run, "ANSWER_WITHIN_S", 30.0)
    last = asyncio.run(check.execute(TESTS))
    assert last.ok and last.data["exit_code"] == 0 and len(world.ran) == 1, "only the edited project was tested"
    assert world.line.gave_back == [1, 2]


def test_a_run_that_changes_the_project_on_its_own_is_not_started_again_and_again(
    tool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file its tests write that git does not ignore changes the state of the project at every call while it runs."""
    check, world = tool
    hold = _held_run(check, monkeypatch)
    monkeypatch.setattr(check_run, "ANSWER_WITHIN_S", 0.2)
    for n in range(5):
        world.state = f"written-by-the-run-{n}"
        assert asyncio.run(check.execute(TESTS)).data["status"] == "running"
    assert world.line.joined == ["check.run"] * 3, "ended and started again twice, then waited for"
    hold.set()
    monkeypatch.setattr(check_run, "ANSWER_WITHIN_S", 30.0)
    last = asyncio.run(check.execute(TESTS))
    assert last.ok and last.data["exit_code"] == 0 and len(world.ran) == 1


@pytest.mark.parametrize("why", ["no git state", "fresh"])
def test_a_verdict_nobody_was_waiting_for_is_not_handed_to_a_later_call(
    tool, monkeypatch: pytest.MonkeyPatch, why: str
) -> None:
    """Without a git state an edit cannot be seen, and fresh asks for a new run: neither takes an old verdict."""
    check, world = tool
    world.state = None if why == "no git state" else "as-it-was"
    hold = _held_run(check, monkeypatch)
    monkeypatch.setattr(check_run, "ANSWER_WITHIN_S", 0.2)
    assert asyncio.run(check.execute(TESTS)).data["status"] == "running"
    hold.set()
    _until(lambda: all(job.future.done() for job in check_run._JOBS.values()))  # it ended with no call waiting
    monkeypatch.setattr(check_run, "ANSWER_WITHIN_S", 30.0)
    later = asyncio.run(check.execute({**TESTS, "fresh": why == "fresh"}))
    assert later.ok and len(world.ran) == 2, "the later call got a run of its own"


def test_a_line_that_cannot_be_used_does_not_stop_the_tests(tool) -> None:
    check, world = tool

    def broken(_label: str) -> int:
        raise sqlite3.OperationalError("database is locked")

    world.line.join = broken
    result = asyncio.run(check.execute(TESTS))
    assert result.ok and result.data["exit_code"] == 0 and len(world.ran) == 1


def test_a_run_says_how_long_it_waited_for_its_turn(tool, monkeypatch: pytest.MonkeyPatch) -> None:
    check, world = tool
    clock = [100.0]

    def look(_ticket: int) -> tuple[bool, int]:
        clock[0] += 42.0  # the wait in the line
        return True, 0

    world.line.look = look
    monkeypatch.setattr(check_run, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    result = asyncio.run(check.execute(TESTS))
    assert "waited 42 s for its turn" in result.data["waited_for_room"]


def test_one_call_answers_well_inside_the_agent_loops_limit_for_a_tool() -> None:
    assert check_run.ANSWER_WITHIN_S + 60 <= 600  # loop_core.default_tool_timeout_s
