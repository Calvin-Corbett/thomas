"""A check still waiting for its turn when Thomas begins to stop leaves at once, as busy, without a strike.

Before, such a check kept waiting through a restart and then ran on the old code, and the change was held with a
strike for a check that never ran. The stop is read through the reservation ledger's watch
(``capacity_ledger.admitted``), so the row is given back as any ended wait gives it back. A check already admitted runs
on as it did, and the server that starts after a restart admits checks as usual.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import threading
import time
from pathlib import Path

import pytest

from tests import hand_in_hold_support
from tests import restart_check_support as support
from thomas.server import capacity_ledger, precard, thomas_project
from thomas.server.app_keys import APP_LOCAL_PORT
from thomas.server.precard import check, workers
from thomas.server.routes import evolve_agent_autopilot as route


def _no_second_look(*_a: object) -> None:  # a check that ran on past its server's stop hands nothing in here
    raise precard.ReviewUnavailable("no second look in this test")


def _settle_stand_ins(monkeypatch: pytest.MonkeyPatch, green: object) -> None:
    """The settle of a Thomas project runs for real up to its check, and that check is the real wait for a turn."""
    monkeypatch.setattr(thomas_project.green_handoff, "size_problems", lambda _eid: [])
    monkeypatch.setattr(precard.review, "held_check", lambda _eid: None)
    monkeypatch.setattr(precard, "check_for_hand_in", lambda _eid: support.admitted(green))
    monkeypatch.setattr(precard.review, "second_look", _no_second_look)


def test_a_check_waiting_behind_another_leaves_as_busy_and_not_costly_soon_after_the_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    green = support.in_line(tmp_path, monkeypatch, wait_s=30)
    stop, result, finished = threading.Event(), [], threading.Event()

    def queued() -> None:
        with workers.generation(stop):
            result.append(support.admitted(green))
        finished.set()

    with support.one_ahead(tmp_path):
        thread = threading.Thread(target=queued)
        thread.start()
        try:
            assert support.until_waiting(3), "the second check must really be waiting"
            began = time.monotonic()
            stop.set()
            assert finished.wait(3), "shutdown must not wait for admission's 30-second timeout"
            assert time.monotonic() - began < 3
            assert len(capacity_ledger.rows()) == 1, "the stopped wait must give back its row"
        finally:
            stop.set()
            thread.join(4)
    assert not thread.is_alive()
    assert (result[0].state, result[0].cause, result[0].costly) == (check.UNAVAILABLE, "busy", False)
    assert capacity_ledger.rows() == []


def test_a_check_admitted_before_the_stop_runs_on_to_its_own_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    green = support.in_line(tmp_path, monkeypatch)
    stop, started, release = threading.Event(), threading.Event(), threading.Event()
    ran: list[str] = []

    def run(*_args: object) -> check.Checked:
        started.set()
        assert release.wait(4)
        ran.append("finished")
        return check.Checked(check.PASSED, "passed")

    monkeypatch.setattr(check, "_against_dev", run)
    with workers.generation(stop):
        # A worker takes the calling context when submitted; exercise that path, not a bare thread.
        async def first() -> None:
            pending = asyncio.create_task(workers.off_the_loop(support.admitted, green))
            assert await asyncio.to_thread(started.wait, 3)
            stop.set()
            release.set()
            assert (await pending).state == check.PASSED

        asyncio.run(first())
    assert ran == ["finished"]
    later = threading.Event()  # the server that starts after the restart admits checks as usual
    with workers.generation(later):
        assert support.admitted(green).state == check.PASSED
    assert ran == ["finished", "finished"]
    assert capacity_ledger.rows() == []


def test_the_servers_stop_sets_the_stopping_state_before_it_waits_for_the_check_threads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[bool] = []
    pending: list[asyncio.Task[bool]] = []
    started, release = threading.Event(), threading.Event()

    def startup_check() -> bool:
        started.set()
        assert release.wait(5)
        return workers.generation_stopping()

    async def setup(_app: object) -> None:
        pending.append(asyncio.create_task(workers.off_the_loop(startup_check)))
        assert await asyncio.to_thread(started.wait, 3)

    async def drain(*_a: object, **_k: object) -> bool:
        seen.append(workers.generation_stopping())
        release.set()
        assert await pending[0]
        return True

    monkeypatch.setattr(workers, "drain", drain)
    support.serve_once(monkeypatch, setup=setup, restart=False)
    assert seen == [True] and not workers.generation_stopping()


def test_the_settle_of_a_change_whose_check_left_raises_a_check_unavailable_error_that_is_not_costly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = hand_in_hold_support.make_project(tmp_path, monkeypatch)
    work, catalog, cid = project
    gen = hand_in_hold_support.book(project)["gen"]
    green = support.in_line(tmp_path, monkeypatch, wait_s=30)
    ran: list[str] = []
    monkeypatch.setattr(check, "_against_dev", lambda *_a: ran.append("ran") or check.Checked(check.PASSED, "passed"))
    _settle_stand_ins(monkeypatch, green)
    stop, raised = threading.Event(), []

    def settle() -> None:
        with workers.generation(stop):
            try:
                thomas_project.settle_if_finished(work, catalog, cid, expected_gen=gen)
            except precard.ReviewUnavailable as exc:
                raised.append(exc)

    thread = threading.Thread(target=settle)
    try:
        with support.one_ahead(tmp_path):
            thread.start()
            assert support.until_waiting(), "the change's check must be waiting for its turn"
            began = time.monotonic()
            stop.set()
            thread.join(5)
            assert not thread.is_alive() and time.monotonic() - began < 5, "the settle waited out the 30 s wait"
    finally:
        stop.set()
        thread.join(10)  # whatever happened, it ends before this test's stand-ins are undone
    assert len(raised) == 1 and isinstance(raised[0], precard.CheckUnavailable), raised
    assert raised[0].costly is False and raised[0].step == "check"
    assert "this server is stopping" in str(raised[0]) and ran == [] and capacity_ledger.rows() == []


@pytest.mark.parametrize("order", [(True, False), (False, True)])
def test_the_stopping_state_stays_with_the_server_that_set_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, order: tuple[bool, bool]
) -> None:
    green = support.in_line(tmp_path, monkeypatch)
    monkeypatch.setattr(check, "_against_dev", lambda *_a: check.Checked(check.PASSED, "passed"))
    states = []
    for stopping in order:

        async def generation() -> str:
            stop = threading.Event()
            with workers.generation(stop):
                if stopping:
                    stop.set()
                result = await workers.off_the_loop(support.admitted, green)
                return result.cause if stopping else result.state

        states.append(asyncio.run(generation()))
    assert states == ["busy" if stopping else check.PASSED for stopping in order]
    assert capacity_ledger.rows() == []


@pytest.mark.parametrize(
    ("turn", "fresh"),
    [("waiting", False), ("waiting", True), ("admitted", False)],
    ids=["waiting", "fresh", "admitted"],
)
def test_a_restart_holds_the_change_in_its_real_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, turn: str, fresh: bool
) -> None:
    """The real stop, the real route settle and the real hold record. A check still waiting for its turn is held at
    its check with no strike, due again for the next server; one already running when the stop gives up waiting for
    it is held with a strike, exactly as before. *fresh*: the settle task does not inherit the server's context."""
    project = hand_in_hold_support.make_project(tmp_path, monkeypatch)
    work, catalog, cid = project
    green = support.in_line(tmp_path, monkeypatch, wait_s=60)
    ran, running, release = [], threading.Event(), threading.Event()

    def against_dev(*_a: object) -> check.Checked:
        ran.append(turn)
        running.set()
        release.wait(10)
        return check.Checked(check.PASSED, "passed")

    monkeypatch.setattr(check, "_against_dev", against_dev)
    _settle_stand_ins(monkeypatch, green)

    async def started(_app: object) -> None:
        settle = route._settle_thomas_project(work, catalog, cid, app={APP_LOCAL_PORT: 8899})
        asyncio.get_running_loop().create_task(settle, context=contextvars.Context() if fresh else None)
        if turn == "waiting":
            assert await asyncio.to_thread(support.until_waiting), "the check must be waiting for its turn"
        else:
            assert await asyncio.to_thread(running.wait, 10), "the check must be running"

    try:
        with contextlib.ExitStack() as line:
            if turn == "waiting":
                line.enter_context(support.one_ahead(tmp_path))
            support.serve_once(monkeypatch, started, drain_s=5 if turn == "waiting" else 1)  # a look a second
    finally:
        release.set()
        idle = support.until_idle()  # the old server's check ends before this test's stand-ins are undone
    assert idle

    held = hand_in_hold_support.row(project) or {}
    assert held.get("state") == "held" and float(held.get("next_at") or 0) > 0, held
    if turn == "waiting":
        assert (held.get("step"), held.get("strikes"), ran) == ("check", 0, []), held
        assert "this server is stopping" in str(held.get("why")) and capacity_ledger.rows() == []
    else:
        assert (held.get("step"), held.get("strikes"), ran) == ("hand-in", 1, ["admitted"]), held
