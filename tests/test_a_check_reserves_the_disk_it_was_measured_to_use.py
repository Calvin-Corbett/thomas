"""A check reserves its measured disk use plus a quarter, with room for scratch copies."""

from __future__ import annotations

import dataclasses
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_checks_are_admitted_side_by_side import green  # noqa: F401 -- isolated ledger and green fixture
from thomas.server import capacity_ledger, green_checkout
from thomas.server.precard import check, slot

GIB = 1024**3
MIB = 1024**2


def test_the_recorded_peak_reserves_one_and_a_quarter_times_its_bytes() -> None:
    assert check.MEASURED_CHECK_DISK_PEAK_BYTES == 484_900_864
    assert check.CHECK_DISK_BYTES == 606_126_080


@pytest.mark.parametrize(
    ("peak", "expected"),
    [(1, 512 * MIB), (500 * MIB + 1, 625 * MIB + 2)],
)
def test_the_reservation_uses_a_floor_or_rounds_one_and_a_quarter_up(peak: int, expected: int) -> None:
    assert check.check_disk_bytes(peak) == expected


@pytest.mark.parametrize(("drive_gib", "expected_mib"), [(8, 512), (20, 1024), (100, 2048)])
def test_the_ledger_scales_its_reserve_to_the_drive(drive_gib: int, expected_mib: int) -> None:
    assert capacity_ledger.disk_floor(drive_gib * GIB) == expected_mib * MIB


def test_a_small_drive_admits_a_check_with_less_than_ten_gib_free() -> None:
    room = capacity_ledger.Room(12 * GIB, None, None, 20 * GIB)
    assert capacity_ledger._short_disk([], check.CHECK_DISK_BYTES, "drive", room) == ""


def test_serial_check_keeps_room_for_its_estimated_writes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    drive = 20 * GIB
    reserve = capacity_ledger.disk_floor(drive)
    monkeypatch.setattr(slot.shutil, "disk_usage", lambda _path: SimpleNamespace(total=drive, free=reserve + 1))
    assert slot.too_little_room(tmp_path, disk_bytes=check.CHECK_DISK_BYTES)
    monkeypatch.setattr(
        slot.shutil, "disk_usage", lambda _path: SimpleNamespace(total=drive, free=reserve + check.CHECK_DISK_BYTES)
    )
    assert slot.too_little_room(tmp_path, disk_bytes=check.CHECK_DISK_BYTES) == ""


def test_serial_check_passes_its_disk_budget_to_admission(
    green: green_checkout.Green, monkeypatch: pytest.MonkeyPatch
) -> None:
    measured: list[int] = []
    monkeypatch.setattr(slot, "clear_leftovers", lambda _age: [])

    def refuse(_root: Path, *, disk_bytes: int = 0) -> str:
        measured.append(disk_bytes)
        return "not enough room"

    monkeypatch.setattr(slot, "too_little_room", refuse)
    result = check._against_dev(green, "dev", "patch", [], "python", False)
    assert result.state == check.UNAVAILABLE
    assert measured == [check.CHECK_DISK_BYTES]


def test_one_gib_above_the_floor_admits_and_runs_a_check(
    green: green_checkout.Green, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        capacity_ledger,
        "measure",
        lambda _where: capacity_ledger.Room(capacity_ledger.FLOOR_BYTES + GIB, None, None),
    )
    ran: list[str] = []
    monkeypatch.setattr(
        check, "_against_dev", lambda *_args: ran.append("ran") or check.Checked(check.PASSED, "checked")
    )

    result = check.check_before_card(green.execution_id)

    assert result.state == check.PASSED
    assert ran == ["ran"]
    assert capacity_ledger.rows() == []


def test_two_gib_above_the_floor_holds_three_checks_at_once(
    green: green_checkout.Green, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        capacity_ledger,
        "measure",
        lambda _where: capacity_ledger.Room(capacity_ledger.FLOOR_BYTES + 2 * GIB, None, None),
    )
    monkeypatch.setattr(check.pool, "size", lambda **_kw: 3 * check.PLACES_PER_CHECK)  # the disk, not the turn limit
    monkeypatch.setattr(green_checkout, "find_green", lambda eid: dataclasses.replace(green, execution_id=eid))
    release = threading.Event()
    entered = threading.Event()
    running: set[str] = set()
    lock = threading.Lock()

    def against_dev(copy: green_checkout.Green, *_args: object) -> check.Checked:
        with lock:
            running.add(copy.execution_id)
            if len(running) == 3:
                entered.set()
        release.wait(10)
        return check.Checked(check.PASSED, "checked")

    monkeypatch.setattr(check, "_against_dev", against_dev)
    monkeypatch.setattr(check, "ADMISSION_WAIT_S", 2.0)
    results: dict[str, check.Checked] = {}
    threads = [
        threading.Thread(target=lambda eid=eid: results.__setitem__(eid, check.check_before_card(eid)))
        for eid in ("first", "second", "third")
    ]
    try:
        for thread in threads:
            thread.start()
        assert entered.wait(5), "three checks should start before any releases its reservation"
        rows = capacity_ledger.rows()
        assert {row["id"] for row in rows if row["state"] == "admitted"} == {
            "check:first",
            "check:second",
            "check:third",
        }
        assert sum(row["disk_bytes"] for row in rows if row["state"] == "admitted") == 3 * check.CHECK_DISK_BYTES
    finally:
        release.set()
        for thread in threads:
            thread.join(10)
    assert set(results) == {"first", "second", "third"}
    assert all(result.state == check.PASSED for result in results.values())
    assert capacity_ledger.rows() == []
