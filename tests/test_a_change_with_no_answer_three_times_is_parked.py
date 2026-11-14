"""Checks that give no answer keep retrying, including beyond the former parking limits."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from tests import hand_in_hold_support as support
from thomas.server import capacity_ledger, hand_in_hold, precard, thomas_project

WHY = "Not checked before this card: the same tests did not run to the end with this change or on dev itself."


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> support.Project:
    return support.make_project(tmp_path, monkeypatch)


@pytest.fixture(autouse=True)
def _own_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(capacity_ledger.ROOT_ENV, str(tmp_path / "ledger"))


@pytest.fixture
def issues(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    from thomas.server import issue_ledger

    found: list[dict[str, Any]] = []
    monkeypatch.setattr(issue_ledger, "record_issue", lambda **kwargs: found.append(kwargs))
    return found


def _no_answer(project: support.Project) -> dict[str, Any] | None:
    """One more check that gave no answer: the row is tried again (``checking``), then held for dev."""
    work, catalog, cid = project
    current = support.row(project)
    if current["state"] != "checking":
        hand_in_hold.change(catalog, cid, current["gen"], {**current, "state": "checking"}, expected=current)
    return hand_in_hold.hold(work, catalog, cid, "check", WHY, costly=False, no_answer=True)


def test_no_answer_keeps_retrying_beyond_both_former_limits(
    project: support.Project, issues: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(precard, "pause_shown", lambda: None)
    work, catalog, cid = project
    support.book(project)

    first, second = _no_answer(project), _no_answer(project)
    assert (first["state"], first["no_answers"], second["state"], second["no_answers"]) == ("held", 1, "held", 2)
    assert issues == []

    for _ in range(hand_in_hold.MAX_TRIES + 2):
        held = _no_answer(project)
        assert held["state"] == "held" and held["strikes"] == 0
    assert held["no_answers"] > hand_in_hold.MAX_TRIES
    assert held["why"] == WHY
    assert held["next_at"] > 0
    state, words = hand_in_hold.phase(work, catalog, cid)
    assert state == "paused" and " of 96" not in words
    assert issues == []
    assert hand_in_hold.retry_after(10**6) == hand_in_hold.RETRY_MAX_S


@pytest.mark.parametrize("failure", ["exception", "non-costly", "unfinished"])
def test_fresh_checks_retry_past_both_caps_without_dev_side_failures(
    project: support.Project, issues: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    from thomas.server import autopilot_hold_tick, autopilot_restart, self_change_status
    from thomas.server.app_keys import APP_LOCAL_PORT
    from thomas.server.routes import evolve_agent_autopilot as route

    work, catalog, cid = project
    booked = support.book(project)
    assert booked.get("no_answers", 0) == 0
    monkeypatch.setattr(autopilot_restart, "_runners_of", lambda _cid: ([], []))
    monkeypatch.setattr(self_change_status, "being_handed_in", lambda _cid: False)
    monkeypatch.setattr(autopilot_hold_tick, "_space_available", lambda _root: True)
    monkeypatch.setattr(autopilot_hold_tick, "_previous_listener_gone", lambda _port: False)
    scheduled: list[dict[str, Any]] = []
    monkeypatch.setattr(autopilot_hold_tick, "_schedule", lambda _app, row, _catalog: scheduled.append(row) or True)
    attempts = 0

    async def unavailable(*_args: Any, **_kwargs: Any) -> None:
        nonlocal attempts
        attempts += 1
        if failure == "exception":
            raise OSError("checker could not open its scratch directory")
        if failure == "non-costly":
            hand_in_hold.hold(work, catalog, cid, "check", "checker unfinished", costly=False)
        # Otherwise leave the row checking so _check's finally block holds it.

    monkeypatch.setattr(route, "_settle_thomas_project", unavailable)
    app = {APP_LOCAL_PORT: 8899}
    asyncio.run(autopilot_hold_tick._check(app, booked, catalog))
    for _ in range(hand_in_hold.MAX_TRIES + 2):
        held = support.row(project)
        assert held["state"] == "held" and held.get("no_answers", 0) == 0
        due = {**held, "next_at": 0}
        assert hand_in_hold.change(catalog, cid, held["gen"], due, expected=held)
        assert asyncio.run(autopilot_hold_tick.tick(app, catalog)) == [cid]
        asyncio.run(autopilot_hold_tick._check(app, scheduled.pop(), catalog))
    held = support.row(project)
    assert held["state"] == "held" and held["tries"] > hand_in_hold.MAX_TRIES
    assert attempts > hand_in_hold.MAX_TRIES and issues == []
    assert held["strikes"] == (0 if failure == "non-costly" else attempts)


def test_holds_that_ran_no_check_do_not_count(project: support.Project, issues: list[dict[str, Any]]) -> None:
    work, catalog, cid = project
    support.book(project)
    _no_answer(project)
    current = support.row(project)
    hand_in_hold.change(catalog, cid, current["gen"], {**current, "state": "checking"}, expected=current)
    busy = hand_in_hold.hold(work, catalog, cid, "check", "another server is checking this change", costly=False)
    assert (busy["state"], busy["no_answers"]) == ("held", 1)
    assert _no_answer(project)["state"] == "held"
    assert issues == []


def test_an_unavailable_check_tells_the_hold_its_cause(
    project: support.Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    work, catalog, cid = project
    support.book(project)
    checked = precard.Checked(precard.UNAVAILABLE, WHY, cause="dev-side", costly=False)
    monkeypatch.setattr(thomas_project.green_handoff, "size_problems", lambda _eid: [])
    monkeypatch.setattr(precard.review, "held_check", lambda _eid: None)
    monkeypatch.setattr(precard, "check_for_hand_in", lambda _eid: checked)

    with pytest.raises(precard.CheckUnavailable) as caught:
        thomas_project.settle_if_finished(work, catalog, cid)

    assert (caught.value.cause, caught.value.costly) == ("dev-side", False)
