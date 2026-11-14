"""A check held for disk room gets its next try when admission becomes possible."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests import hand_in_hold_support as support
from thomas.server import autopilot_hold_tick as tick_module
from thomas.server import capacity_ledger, green_checkout, hand_in_hold
from thomas.server.precard import check

NOW = 1000.0


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> support.Project:
    monkeypatch.setenv(capacity_ledger.ROOT_ENV, str(tmp_path / "ledger"))
    monkeypatch.setattr(hand_in_hold, "clock", lambda: NOW)
    return support.make_project(tmp_path, monkeypatch)


def _held(project: support.Project, why: str, *, step: str = "check") -> dict[str, Any]:
    work, catalog, cid = project
    booked = support.book(project)
    changed = {**booked, "state": "held", "step": step, "why": why, "next_at": NOW + 870, "at": NOW}
    assert hand_in_hold.change(catalog, cid, booked["gen"], changed, expected=booked)
    assert support.row(project) == changed
    return changed


def _fake_room(monkeypatch: pytest.MonkeyPatch, *, free: int) -> tuple[list[str], list[str]]:
    calls: list[str] = []
    started: list[str] = []

    def rows(root: Path | None = None) -> list[dict[str, Any]]:
        calls.append("rows")
        return []

    def measure(where: Path) -> capacity_ledger.Room:
        calls.append("measure")
        return capacity_ledger.Room(free, None, None)

    monkeypatch.setattr(capacity_ledger, "_live", lambda _place: (rows(_place), False))
    monkeypatch.setattr(capacity_ledger, "measure", measure)
    monkeypatch.setattr(green_checkout, "green_root", lambda: Path("greens"))
    monkeypatch.setattr(tick_module, "_schedule", lambda _app, held, _catalog: started.append(held["cid"]) or True)
    return calls, started


def _more_rows(project: support.Project, count: int) -> list[str]:
    """Add independent held rows with the same valid turn; no real runner is started."""
    _, catalog, cid = project
    first = support.row(project)
    assert first is not None
    ids = [cid]
    rows = hand_in_hold.read(catalog)
    for index in range(1, count):
        new_id = f"held-{index}"
        rows.append({**first, "cid": new_id})
        ids.append(new_id)
    hand_in_hold.write(catalog, rows)
    return ids


def test_room_return_triggers_one_try_without_waiting_870_seconds(
    project: support.Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = _held(project, "there was no room to check it: disk is short")
    calls, started = _fake_room(monkeypatch, free=capacity_ledger.FLOOR_BYTES + check.CHECK_DISK_BYTES - 1)
    assert support.tick(project) == []
    assert started == [] and support.row(project) == before
    monkeypatch.setattr(
        capacity_ledger,
        "measure",
        lambda _where: (
            calls.append("measure")
            or capacity_ledger.Room(capacity_ledger.FLOOR_BYTES + check.CHECK_DISK_BYTES, None, None)
        ),
    )
    assert support.tick(project) == [project[2]]
    assert started == [project[2]]
    after = support.row(project)
    assert after is not None
    assert (after["tries"], after["strikes"], after["next_at"]) == (
        before["tries"] + 1,
        before["strikes"],
        NOW + hand_in_hold.RETRY_S,
    )


def test_a_second_no_room_hold_cannot_retry_early_again(
    project: support.Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    _held(project, "there was no room to check it: disk is short")
    _, started = _fake_room(monkeypatch, free=capacity_ledger.FLOOR_BYTES + check.CHECK_DISK_BYTES)
    assert support.tick(project) == [project[2]]
    checking = support.row(project)
    assert checking is not None
    held = hand_in_hold.hold(project[0], project[1], project[2], "check", check.NO_ROOM_PHRASE + ": disk is short")
    assert held is not None and held["state"] == "held"
    assert held["next_at"] == NOW + hand_in_hold.RETRY_S
    monkeypatch.setattr(hand_in_hold, "clock", lambda: NOW + 30)
    assert support.tick(project) == []
    assert support.row(project) == held and started == [project[2]]


def test_due_no_room_try_can_retry_early_after_room_returns(
    project: support.Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _held(project, check.NO_ROOM_PHRASE + ": disk is short")
    due = {**first, "next_at": NOW}
    assert hand_in_hold.change(project[1], project[2], first["gen"], due, expected=first)
    _, started = _fake_room(monkeypatch, free=capacity_ledger.FLOOR_BYTES)
    assert support.tick(project) == [project[2]]  # a due try does not use the early admission preflight
    held = hand_in_hold.hold(project[0], project[1], project[2], "check", check.NO_ROOM_PHRASE + ": disk is short")
    assert held is not None and held["next_at"] == NOW + hand_in_hold.RETRY_S
    monkeypatch.setattr(
        capacity_ledger,
        "measure",
        lambda _where: capacity_ledger.Room(capacity_ledger.FLOOR_BYTES + check.CHECK_DISK_BYTES, None, None),
    )
    monkeypatch.setattr(hand_in_hold, "clock", lambda: NOW + 30)
    assert support.tick(project) == [project[2]]  # room returned before next_at
    assert started == [project[2], project[2]]
    again = support.row(project)
    assert again is not None
    assert (again["tries"], again["strikes"], again["next_at"]) == (
        held["tries"] + 1,
        held["strikes"],
        NOW + 30 + hand_in_hold.RETRY_S,
    )


@pytest.mark.parametrize(
    ("step", "why"),
    [("check", "another server is checking it"), ("second look", "your plan's usage limit is reached")],
)
def test_other_held_reasons_wait_until_due(
    project: support.Project, monkeypatch: pytest.MonkeyPatch, step: str, why: str
) -> None:
    before = _held(project, why, step=step)
    calls, started = _fake_room(monkeypatch, free=capacity_ledger.FLOOR_BYTES + check.CHECK_DISK_BYTES)
    assert support.tick(project) == []
    assert support.row(project) == before and started == [] and calls == []


def test_three_waiters_share_one_ledger_read_and_measure(
    project: support.Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    _held(project, "there was no room to check it: disk is short")
    calls, started = _fake_room(monkeypatch, free=capacity_ledger.FLOOR_BYTES)
    ids = _more_rows(project, 3)
    # These rows must be current, but need not have separate conversations for this preflight.
    monkeypatch.setattr(hand_in_hold, "still_current", lambda *_args, **_kwargs: True)
    assert support.tick(project) == []
    assert started == [] and calls.count("rows") == calls.count("measure") == 1
    assert all(hand_in_hold.row(project[1], cid)["tries"] == 1 for cid in ids)


@pytest.mark.parametrize("broken", ["rows", "measure"])
def test_unreadable_room_preserves_every_early_waiter(
    project: support.Project, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, broken: str
) -> None:
    before = _held(project, "there was no room to check it: disk is short")
    calls, started = _fake_room(monkeypatch, free=capacity_ledger.FLOOR_BYTES + check.CHECK_DISK_BYTES)

    def unavailable(*_args: Any, **_kwargs: Any) -> Any:
        calls.append(broken)
        raise OSError("room cannot be read")

    if broken == "rows":
        monkeypatch.setattr(capacity_ledger, "_live", lambda _place: unavailable())
    else:
        monkeypatch.setattr(capacity_ledger, "measure", unavailable)
    assert support.tick(project) == []
    assert support.row(project) == before and started == []
    assert (support.row(project)["tries"], support.row(project)["strikes"], support.row(project)["next_at"]) == (
        before["tries"],
        before["strikes"],
        before["next_at"],
    )
    assert "could not be read" in caplog.text


def test_both_no_room_answers_keep_their_words_and_do_not_strike(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    green = green_checkout.Green("green-1", tmp_path, tmp_path, "base", tmp_path)
    monkeypatch.setenv(capacity_ledger.ROOT_ENV, str(tmp_path / "ledger"))
    monkeypatch.setattr(green_checkout, "green_root", lambda: tmp_path)
    monkeypatch.setattr(check.proofs, "select", lambda *_args, **_kwargs: type("Selection", (), {"files": []})())

    def refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise capacity_ledger.NotAdmitted("disk is short", waited=False)

    monkeypatch.setattr(capacity_ledger, "admitted", refuse)
    ledger = check._admitted(green, "dev", "patch", [], "python")
    monkeypatch.setattr(check.slot, "clear_leftovers", lambda _age: None)
    monkeypatch.setattr(check.slot, "too_little_room", lambda _root, **_kw: "the drive has 1.0 GB free")
    floor = check._against_dev(green, "dev", "patch", [], "python")
    assert check.NO_ROOM_PHRASE == "there was no room to check it"
    assert ledger.line.endswith(f"{check.NO_ROOM_PHRASE}: disk is short.")
    assert floor.line.endswith(f"{check.NO_ROOM_PHRASE}: the drive has 1.0 GB free.")
    assert (ledger.cause, ledger.costly) == ("low-disk", False)
    assert (floor.cause, floor.costly) == ("low-disk", False)
