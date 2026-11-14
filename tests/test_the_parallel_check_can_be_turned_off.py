"""THOMAS_PRECARD_PARALLEL=off brings back one check at a time (spec 2026-10-12 Part 1 item 11).

Off is the earlier machinery: today's per-server lock, no ledger, file arguments, the per-copy worker formula and the
120-file cap. It never reaches a nested test run.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from tests.test_an_unavailable_check_names_its_cause import green  # noqa: F401 -- the fixture
from thomas.server import capacity_ledger, green_checkout, precard
from thomas.server.precard import check, clocks, pool, review
from thomas.server.proof import environment


def test_the_parallel_switch_hears_the_same_off_words_as_the_other_two() -> None:
    assert pool._OFF == check._OFF == review._OFF


def _two_at_once(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    together = threading.Barrier(2, timeout=1.0)
    outcomes: list[str] = []

    def decide(_execution_id: str, _files: object, _shared: object = None) -> check.Checked:
        try:
            together.wait()
            outcomes.append("together")
        except threading.BrokenBarrierError:
            outcomes.append("alone")
        return check.Checked(check.PASSED, "checked")

    monkeypatch.setattr(check, "_decide", decide)
    threads = [threading.Thread(target=check.check_before_card, args=(eid,)) for eid in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    return outcomes


def test_with_parallel_off_two_checks_never_overlap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(check.CHECK_ENV, "on")
    monkeypatch.setenv(pool.PARALLEL_ENV, "off")

    assert _two_at_once(monkeypatch) == ["alone", "alone"]


def test_with_parallel_on_two_checks_run_side_by_side(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(check.CHECK_ENV, "on")
    monkeypatch.delenv(pool.PARALLEL_ENV, raising=False)

    assert _two_at_once(monkeypatch) == ["together", "together"]


def test_with_parallel_off_the_ledger_is_never_touched(
    green: green_checkout.Green, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(pool.PARALLEL_ENV, "off")

    def never(*_a: object, **_k: object) -> None:
        raise AssertionError("the ledger was used with the switch off")

    monkeypatch.setattr(capacity_ledger, "admitted", never)  # the module itself: a guard before SC3 as after
    monkeypatch.setattr(check, "_against_dev", lambda *_a: check.Checked(check.PASSED, "checked"))

    assert check.check_before_card("green-1").state == check.PASSED
    assert not list((tmp_path / "ledger").glob("reservations.json"))


@pytest.mark.parametrize("off", [True, False])
def test_the_clocks_say_how_the_check_was_admitted(
    green: green_checkout.Green, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, off: bool
) -> None:
    if off:
        monkeypatch.setenv(pool.PARALLEL_ENV, "off")
    monkeypatch.setattr(check, "_against_dev", lambda *_a: check.Checked(check.PASSED, "checked"))

    with clocks.recording(tmp_path / "catalog", "conversation") as record:
        clocks.note("execution_id", "green-1")
        check.check_before_card("green-1")

    assert record["parallel"] is (not off)
    assert {"slot_wait", "in_slot"} <= set(record["stages"])


def test_with_parallel_off_a_full_disk_still_refuses_without_a_strike(
    green: green_checkout.Green, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(pool.PARALLEL_ENV, "off")
    monkeypatch.setattr(check.slot, "too_little_room", lambda _root, **_kw: "the drive has 1.0 GB free")

    checked = precard.check_before_card("green-1")

    assert (checked.state, checked.cause, checked.costly) == (check.UNAVAILABLE, "low-disk", False)


def test_the_switch_never_reaches_a_nested_test_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(pool.PARALLEL_ENV, "off")

    assert pool.PARALLEL_ENV not in environment.sandbox_env(tmp_path, tmp_path / "d")
