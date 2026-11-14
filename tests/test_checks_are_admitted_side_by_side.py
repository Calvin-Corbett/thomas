"""Checks are admitted side by side against the machine-wide ledger (spec 2026-10-12 Part 1 item 5).

One in-process lock ran one check at a time. Now a check is sized by the files it selects on the green's own tree,
waits in the ledger's line (fewest files first, aging, 15 minutes goes next), and starts when free disk minus what is
promised stays at or above the 10 GiB floor. A check that cannot be admitted is held without a strike.
"""

from __future__ import annotations

import contextlib
import dataclasses
import inspect
import json
import math
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_a_change_is_checked_before_your_card import (  # noqa: F401 -- base_repo and world are fixtures
    CLEAN_ADDER,
    CLEAN_TEST,
    EXECUTION,
    base_repo,
    world,
)
from tests.test_an_unavailable_check_names_its_cause import green  # noqa: F401 -- the fixture
from thomas.server import capacity_ledger, green_checkout, precard
from thomas.server.precard import check, clocks, pool
from thomas.server.proof import Selection, selection

SPECS = Path(__file__).resolve().parents[1] / "docs" / "superpowers" / "specs"
DISK_RECORD = SPECS / "2026-10-12-praxis-production-line-check-disk.json"  # Task 7 Step 7's measurement


def test_two_checks_overlap_when_parallel_is_on(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(pool.PARALLEL_ENV, raising=False)
    second = green_checkout.create_green(blue=world.blue, execution_id="thomas-checked2")
    for copy in (world.green, second):
        for rel, text in {"pkg/adder.py": CLEAN_ADDER, "tests/test_adder.py": CLEAN_TEST}.items():
            (copy.work / rel).write_text(text, encoding="utf-8")
    together = threading.Barrier(2, timeout=60)
    real = check._against_dev

    def side_by_side(copy: green_checkout.Green, *args: object) -> check.Checked:
        together.wait()  # one check at a time never gets past this
        return real(copy, *args)

    monkeypatch.setattr(check, "_against_dev", side_by_side)
    results: dict[str, check.Checked] = {}
    threads = [
        threading.Thread(target=lambda eid=eid: results.__setitem__(eid, precard.check_before_card(eid)))
        for eid in (EXECUTION, second.execution_id)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(300)

    assert {eid: r.state for eid, r in results.items()} == {EXECUTION: "passed", second.execution_id: "passed"}


def test_selection_runs_before_admission_on_the_greens_own_tree(
    green: green_checkout.Green, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[tuple[str, object]] = []
    monkeypatch.setattr(check.proofs, "select", lambda root, _changed, **_k: order.append(("select", Path(root)))
                        or Selection(("tests/a.py", "tests/b.py", "tests/c.py"), ()))  # fmt: skip
    real = capacity_ledger.admitted
    asked: list[tuple[str, dict[str, object]]] = []

    def admitted(job_id: str, **kwargs: object):
        order.append(("admitted", kwargs["files"]))
        asked.append((job_id, kwargs))
        return real(job_id, **kwargs)

    monkeypatch.setattr(check.capacity_ledger, "admitted", admitted)
    monkeypatch.setattr(check, "_against_dev", lambda *_a: check.Checked(check.PASSED, "checked"))

    assert check.check_before_card("green-1").state == check.PASSED
    assert order[:2] == [("select", green.work), ("admitted", 3)]
    [(job_id, kwargs)] = asked
    assert job_id == "check:green-1" and kwargs["kind"] == "check", "a check waits in the checks' own line"
    assert kwargs["disk_bytes"] == check.CHECK_DISK_BYTES and kwargs["wait_s"] == check.ADMISSION_WAIT_S
    assert kwargs["where"] == green_checkout.green_root(), "the drive its copies of dev go on"


@pytest.mark.parametrize(("waited", "cause"), [(False, "low-disk"), (True, "busy")])
def test_a_check_that_cannot_be_admitted_is_held_without_a_strike(
    green: green_checkout.Green, monkeypatch: pytest.MonkeyPatch, waited: bool, cause: str
) -> None:
    def refuse(_job_id: str, **_kwargs: object):
        raise capacity_ledger.NotAdmitted("the drive has 9.0 GB free", waited=waited)

    monkeypatch.setattr(check.capacity_ledger, "admitted", refuse)

    checked = check.check_before_card("green-1")

    assert (checked.state, checked.cause, checked.costly) == (check.UNAVAILABLE, cause, False)
    assert checked.line.startswith("Not checked before this card")


def test_with_room_for_one_reservation_a_second_check_waits_and_is_held_without_a_strike(
    green: green_checkout.Green, monkeypatch: pytest.MonkeyPatch
) -> None:
    room = capacity_ledger.Room(capacity_ledger.FLOOR_BYTES + check.CHECK_DISK_BYTES, None, None)
    monkeypatch.setattr(capacity_ledger, "measure", lambda _where: room)  # the floor and exactly one check's room
    monkeypatch.setattr(capacity_ledger, "POLL_S", 0.05)
    monkeypatch.setattr(check, "ADMISSION_WAIT_S", 2.0)
    monkeypatch.setattr(green_checkout, "find_green", lambda eid: dataclasses.replace(green, execution_id=eid))
    answered = threading.Event()

    def against_dev(copy: green_checkout.Green, *_a: object) -> check.Checked:
        if copy.execution_id == "first":
            answered.wait(8)  # holds its reservation until the second check has its answer
        return check.Checked(check.PASSED, "checked")

    monkeypatch.setattr(check, "_against_dev", against_dev)
    results: dict[str, check.Checked] = {}
    first = threading.Thread(target=lambda: results.__setitem__("first", check.check_before_card("first")))
    first.start()
    try:
        ends = time.monotonic() + 10
        while not any(row["id"] == "check:first" and row["state"] == "admitted" for row in capacity_ledger.rows()):
            assert time.monotonic() < ends, "the first check was never admitted"
            time.sleep(0.02)
        results["second"] = check.check_before_card("second")
    finally:
        answered.set()
        first.join(30)

    second = results["second"]
    assert (second.state, second.cause, second.costly) == (check.UNAVAILABLE, "busy", False)
    assert results["first"].state == check.PASSED


def test_a_second_try_of_a_running_check_never_holds_up_others(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A held hand-in tried again while its first check still runs (a restart's wait ran out) waits for that one."""
    monkeypatch.setattr(capacity_ledger, "POLL_S", 0.05)
    roomy = capacity_ledger.Room(100 * 1024**3, None, None)
    line = {"kind": "check", "where": tmp_path, "room": lambda _w: roomy, "root": tmp_path / "ledger"}
    running, done = threading.Event(), threading.Event()

    def first() -> None:
        with capacity_ledger.admitted("check:X", files=50, wait_s=5, **line):
            running.set()
            done.wait(15)

    def again() -> None:
        with capacity_ledger.admitted("check:X", files=1, wait_s=20, **line):  # fewest files: the head of the line
            pass

    threads = [threading.Thread(target=first), threading.Thread(target=again)]
    threads[0].start()
    try:
        assert running.wait(5)
        threads[1].start()
        ends = time.monotonic() + 10
        while sum(row["id"] == "check:X" for row in capacity_ledger.rows(tmp_path / "ledger")) < 2:
            assert time.monotonic() < ends, "the second try of check:X never took its place in line"
            time.sleep(0.02)
        began = time.monotonic()
        with capacity_ledger.admitted("check:Y", files=200, wait_s=3, **line):
            took = time.monotonic() - began
    finally:
        done.set()
        for thread in threads:
            thread.join(30)

    assert took < 2.0, "check:Y waited behind a second try of check:X"


def test_a_check_runs_against_dev_as_it_is_when_its_turn_comes(
    green: green_checkout.Green, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A check can wait up to an hour for its turn while dev moves on: it reads the tip again once admitted."""
    tips, used = ["dev-1"], []

    @contextlib.contextmanager
    def turn(_job_id: str, **_kwargs: object) -> Iterator[dict[str, object]]:
        tips[0] = "dev-2"  # dev moved on while this check waited in line
        yield {}

    monkeypatch.setattr(check.green_handoff, "dev_tip", lambda _eid: tips[0])
    monkeypatch.setattr(check.capacity_ledger, "admitted", turn)
    monkeypatch.setattr(check, "_against_dev", lambda _g, tip, *_a: used.append(tip) or check.Checked(check.PASSED, ""))

    checked = check.check_before_card("green-1")

    assert used == ["dev-2"] and checked.dev_tip == "dev-2", "checked against dev as it is, and recorded so"


def test_a_dev_tip_that_cannot_be_read_once_admitted_is_incomplete(
    green: green_checkout.Green, monkeypatch: pytest.MonkeyPatch
) -> None:
    tips, ran = ["dev-1"], []

    @contextlib.contextmanager
    def turn(_job_id: str, **_kwargs: object) -> Iterator[dict[str, object]]:
        tips[0] = ""
        yield {}

    monkeypatch.setattr(check.green_handoff, "dev_tip", lambda _eid: tips[0])
    monkeypatch.setattr(check.capacity_ledger, "admitted", turn)
    monkeypatch.setattr(check, "_against_dev", lambda *_a: ran.append("ran") or check.Checked(check.PASSED, ""))

    checked = check.check_before_card("green-1")

    assert (checked.state, checked.cause, checked.costly, ran) == (check.UNAVAILABLE, "incomplete", True, [])


def test_the_clocks_say_what_the_admission_found(green: green_checkout.Green, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(check, "_against_dev", lambda *_a: check.Checked(check.PASSED, "checked"))

    with clocks.recording(tmp_path / "catalog", "conversation") as record:
        clocks.note("execution_id", "green-1")
        check.check_before_card("green-1")

    assert record["parallel"] is True and record["admission_files"] >= 0
    assert record["free_disk_at_admission_bytes"] > 0 and record["check_cause"] == ""
    assert {"selection_before_admission", "slot_wait", "in_slot"} <= set(record["stages"])


def test_a_check_reserves_the_larger_of_512_mib_and_one_and_a_quarter_times_the_measured_peak() -> None:
    recorded = json.loads(DISK_RECORD.read_text(encoding="utf-8"))["check_disk_peak_bytes"]

    assert check.MEASURED_CHECK_DISK_PEAK_BYTES == recorded > 0, "the figure Step 0's load run recorded"
    assert max(512 * 1024**2, math.ceil(1.25 * recorded)) == check.CHECK_DISK_BYTES


def test_a_ledger_that_cannot_be_used_holds_the_check_without_a_strike_and_runs_nothing(
    green: green_checkout.Green, monkeypatch: pytest.MonkeyPatch
) -> None:
    """As a shard does (``pool.runner``): an unusable ledger is no place, never a check run unreserved."""
    ran: list[str] = []

    def unusable(_job_id: str, **_kwargs: object):
        raise TimeoutError("the ledger's file lock stayed held")

    monkeypatch.setattr(check.capacity_ledger, "admitted", unusable)
    monkeypatch.setattr(check, "_against_dev", lambda *_a: ran.append("ran") or check.Checked(check.PASSED, "checked"))

    checked = check.check_before_card("green-1")

    assert (checked.state, checked.cause, checked.costly) == (check.UNAVAILABLE, "busy", False)
    assert ran == [], "a check never runs without its reservation"


def test_the_turn_is_timed_apart_from_the_wait_for_it(
    green: green_checkout.Green, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``in_slot`` is a check's turn, as the timeline counts checks running at once; ``slot_wait`` is its wait."""

    @contextlib.contextmanager
    def slow_turn(_job_id: str, **_kwargs: object) -> Iterator[dict[str, object]]:
        time.sleep(0.3)  # waiting in the ledger's line
        yield {}

    monkeypatch.setattr(check.capacity_ledger, "admitted", slow_turn)
    monkeypatch.setattr(check, "_against_dev", lambda *_a: check.Checked(check.PASSED, "checked"))

    with clocks.recording(tmp_path / "catalog", "conversation") as record:
        clocks.note("execution_id", "green-1")
        check.check_before_card("green-1")

    stages = record["stages"]
    assert stages["slot_wait"]["seconds"] >= 0.25
    assert stages["slot_wait"]["end"] <= stages["in_slot"]["start"], "the wait is never counted as running"


def test_a_free_disk_reading_that_fails_never_fails_the_check(
    green: green_checkout.Green, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    @contextlib.contextmanager
    def turn(_job_id: str, **_kwargs: object) -> Iterator[dict[str, object]]:
        yield {}

    def unreadable(_where: Path) -> capacity_ledger.Room:
        raise OSError("the drive could not be read")

    monkeypatch.setattr(check.capacity_ledger, "admitted", turn)
    monkeypatch.setattr(check.capacity_ledger, "measure", unreadable)
    monkeypatch.setattr(check, "_against_dev", lambda *_a: check.Checked(check.PASSED, "checked"))

    with clocks.recording(tmp_path / "catalog", "conversation") as record:
        clocks.note("execution_id", "green-1")
        assert check.check_before_card("green-1").state == check.PASSED

    assert record["free_disk_at_admission_bytes"] is None, "not measured, and the check stands"


def test_a_cache_another_check_clears_mid_read_never_fails_its_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Checks select their tests on the check threads side by side now, sharing one parsed-imports cache."""

    class ClearedBetween(dict):
        def __contains__(self, key: object) -> bool:
            found = super().__contains__(key)
            self.clear()  # another check's selection filled the cache to its limit and cleared it just now
            return found

    monkeypatch.setattr(selection, "_PARSED", ClearedBetween())
    first = selection._imported("import json\n")

    assert selection._imported("import json\n") == first == frozenset({"json"})


def test_checks_beside_a_busy_pool_wait_their_turn_instead_of_starving_together() -> None:
    # 2026-10-23: six checks admitted at once over sixteen places; none finished within its hour, for hours.
    assert check.check_limit(16) == 2
    assert check.check_limit(48) == 8
    assert check.check_limit(4) == 2  # two may always run side by side
    source = inspect.getsource(check)
    assert "limit=check_limit(pool.size())" in source


def test_a_third_check_waits_while_two_hold_the_places(tmp_path: Path) -> None:
    room = capacity_ledger.Room(free_disk=10**12, total_ram=64 * 2**30, available_ram=32 * 2**30)
    with capacity_ledger.admitted(
        "check:a", kind="check", where=tmp_path, limit=2, root=tmp_path, room=lambda _p: room
    ):
        with capacity_ledger.admitted(
            "check:b", kind="check", where=tmp_path, limit=2, root=tmp_path, room=lambda _p: room
        ):
            with pytest.raises(capacity_ledger.NotAdmitted, match="all 2 places are in use"):
                with capacity_ledger.admitted(
                    "check:c", kind="check", where=tmp_path, limit=2, root=tmp_path, room=lambda _p: room, wait_s=0.5
                ):
                    pass
