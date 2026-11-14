"""Planner discovery must not call ledger readers inside a queue transaction."""

from __future__ import annotations

from pathlib import Path

import pytest

from thomas.server import capacity_ledger as ledger
from thomas.server import capacity_ledger_locks as locks
from thomas.server import self_improvement_planner as planner
from thomas.server import self_project_queue as queue
from thomas.server import self_project_queue_tick as tick


@pytest.fixture
def isolated_queue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(ledger, "folder", lambda: tmp_path / "ledger")
    monkeypatch.setenv("THOMAS_SELF_IMPROVEMENT_PLANNER", "on")
    monkeypatch.setattr(planner, "propose", lambda *args, **kwargs: [])
    monkeypatch.setattr(planner, "propose_wider", lambda root: [])
    original = locks._lock

    class Tripwire:
        def __enter__(self):
            # Use the actual shared mutex, but fail rather than hang if a
            # planner callback tries to acquire it while the queue holds it.
            assert original.acquire(blocking=False), "planner reentered the shared ledger mutex"
            return self

        def __exit__(self, *exc):
            original.release()

    monkeypatch.setattr(locks, "_lock", Tripwire())
    return tmp_path


def proposal(source_id: str = "test:one") -> dict[str, str]:
    return {"source": "test", "source_id": source_id, "key": source_id, "request": "Fix one proven defect."}


@pytest.mark.parametrize("reader", ["propose", "capacity", "propose_wider"])
def test_discovery_can_read_ledger(isolated_queue: Path, monkeypatch: pytest.MonkeyPatch, reader: str) -> None:
    calls = []

    def read_ledger(*args, **kwargs):
        calls.append(reader)
        assert ledger.rows() == []
        return True if reader == "capacity" else [proposal()]

    capacity = True
    if reader == "capacity":
        capacity = read_ledger
    else:
        monkeypatch.setattr(planner, reader, read_ledger)
    added = planner.scan(isolated_queue, 8899, wider_when_empty=capacity)
    assert calls == [reader]
    assert len(added) == (0 if reader == "capacity" else 1)


def test_tick_capacity_callback_can_read_ledger(isolated_queue: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tick.machine_capacity, "_memory", lambda: (64 * 1024**3, 48 * 1024**3))
    monkeypatch.setattr(tick.machine_capacity, "admission_refusal", lambda active: None)
    monkeypatch.setattr(tick.self_project_routes, "running_projects", lambda app: [])
    monkeypatch.setattr(ledger, "measure", lambda root: ledger.Room(100 * 1024**3, None, None))
    monkeypatch.setattr(planner, "propose_wider", lambda root: [proposal()])
    original_rows = ledger.rows
    calls = []

    def rows():
        calls.append("ledger")
        return original_rows()

    monkeypatch.setattr(ledger, "rows", rows)
    added = planner.scan(isolated_queue, 8899, wider_when_empty=lambda: tick._room_for_wider_scan({}))
    assert calls == ["ledger"]
    assert len(added) == 1


def test_evidence_skips_wider_capacity_probe(isolated_queue: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(planner, "propose", lambda *args, **kwargs: [proposal()])

    def unexpected():
        pytest.fail("capacity should not be probed when evidence already supplied work")

    assert len(planner.scan(isolated_queue, 8899, wider_when_empty=unexpected)) == 1


@pytest.mark.parametrize("race", ["disabled", "enqueued", "duplicate", "key_duplicate"])
def test_wider_booking_rechecks_current_queue(isolated_queue: Path, monkeypatch: pytest.MonkeyPatch, race: str) -> None:
    def wider(root):
        assert ledger.rows() == []

        def update(data):
            if race == "disabled":
                data["planner"]["enabled"] = False
            else:
                row = queue.new_entry("Concurrent work", {}, "", 8899)
                if race == "duplicate":
                    row["source_id"] = proposal()["source_id"]
                    data["started"].append(row)
                elif race == "key_duplicate":
                    row["dedupe_key"] = proposal()["key"]
                    row["source_id"] = "different-evidence"
                    data["given_up"].append(row)
                else:
                    data["queued"].append(row)

        queue.change(root, update)
        return [proposal()]

    monkeypatch.setattr(planner, "propose_wider", wider)
    assert planner.scan(isolated_queue, 8899, wider_when_empty=True) == []
    state = queue.read(isolated_queue)
    assert len(state["queued"]) == (1 if race == "enqueued" else 0)
    assert state["planner"]["enabled"] is (race != "disabled")


@pytest.mark.parametrize("blocked", ["queued", "capacity"])
def test_wider_discovery_respects_gates(isolated_queue: Path, monkeypatch: pytest.MonkeyPatch, blocked: str) -> None:
    if blocked == "queued":
        queue.change(isolated_queue, lambda data: data["queued"].append(queue.new_entry("Existing work", {}, "", 8899)))
    calls = []

    def capacity():
        calls.append("capacity")
        return False

    def unexpected(*args, **kwargs):
        pytest.fail("wider discovery must respect queue and capacity gates")

    monkeypatch.setattr(planner, "propose_wider", unexpected)
    assert planner.scan(isolated_queue, 8899, wider_when_empty=capacity) == []
    assert calls == ([] if blocked == "queued" else ["capacity"])


@pytest.mark.parametrize("disabled", [True, False])
def test_evidence_booking_rechecks_state(isolated_queue: Path, monkeypatch: pytest.MonkeyPatch, disabled: bool) -> None:
    def propose(root, **kwargs):
        def update(data):
            if disabled:
                data["planner"]["enabled"] = False
            else:
                row = queue.new_entry("Already handled", {}, "", 8899)
                row["source_id"] = proposal()["source_id"]
                data["started"].append(row)

        queue.change(root, update)
        return [proposal()]

    monkeypatch.setattr(planner, "propose", propose)
    monkeypatch.setattr(planner, "propose_wider", lambda root: [proposal("wider-evidence")])
    added = planner.scan(isolated_queue, 8899, wider_when_empty=True)
    assert [row["source_id"] for row in added] == ([] if disabled else ["wider-evidence"])
