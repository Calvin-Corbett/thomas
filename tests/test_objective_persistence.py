"""Tests for CAP-010 long-horizon objective persistence.

Proves the exact Level-2 acceptance line: persist objective snapshots, run
periodic drift audits, and prove exact resume after restart.
"""

from __future__ import annotations

import json

import pytest

from thomas.memory.objective_persistence import (
    DriftReport,
    ObjectiveNotFoundError,
    ObjectiveSnapshot,
    ObjectiveStore,
    ResumeState,
)


@pytest.fixture
def store_path(tmp_path):
    return tmp_path / "objectives.sqlite3"


@pytest.fixture
def store(store_path):
    s = ObjectiveStore(path=store_path)
    try:
        yield s
    finally:
        s.close()


def _sample(store: ObjectiveStore) -> ObjectiveSnapshot:
    return store.snapshot(
        "obj-ship-cap010",
        goal="Ship long-horizon task persistence to Level 2",
        constraints=[
            "Do not touch protected files",
            "ruff check must pass",
        ],
        acceptance_criteria=[
            "Persist objective snapshots",
            "Run periodic drift audits",
            "Prove exact resume after restart",
        ],
        progress={"phase": "implementation", "files_written": 1, "criteria_done": []},
        created_at=1_700_000_000.5,
    )


# -- snapshot persist + load round-trip ------------------------------------


def test_snapshot_persist_and_load_round_trip(store):
    snap = _sample(store)
    loaded = store.latest("obj-ship-cap010")
    assert loaded == snap
    assert loaded.revision == 1
    assert loaded.goal == "Ship long-horizon task persistence to Level 2"
    assert loaded.constraints == snap.constraints
    assert loaded.acceptance_criteria == snap.acceptance_criteria
    assert loaded.progress == snap.progress
    assert loaded.created_at == 1_700_000_000.5


# -- exact resume across a simulated restart -------------------------------


def test_exact_resume_after_simulated_restart(store_path):
    # Process #1: create the objective, then "crash" (close the store).
    first = ObjectiveStore(path=store_path)
    original = _sample(first)
    stored_bytes = original.canonical_json
    first.close()

    # Process #2: brand-new store instance on the same file.
    second = ObjectiveStore(path=store_path)
    try:
        resumed = second.resume("obj-ship-cap010")
    finally:
        second.close()

    assert isinstance(resumed, ResumeState)
    # Deep equality of the objective + progress.
    assert resumed.snapshot == original
    assert resumed.progress == original.progress
    # Byte-for-byte faithful to what was persisted.
    assert resumed.stored_json == stored_bytes
    assert resumed.snapshot.canonical_json == stored_bytes
    assert resumed.is_exact()


def test_stored_bytes_match_disk(store_path):
    first = ObjectiveStore(path=store_path)
    original = _sample(first)
    first.close()

    # Read the raw DB row and confirm resume reproduces the exact stored bytes.
    import sqlite3

    conn = sqlite3.connect(store_path)
    try:
        row = conn.execute(
            "SELECT payload_json FROM objective_snapshots WHERE objective_id = ? ORDER BY revision DESC LIMIT 1",
            ("obj-ship-cap010",),
        ).fetchone()
    finally:
        conn.close()
    on_disk = row[0]

    second = ObjectiveStore(path=store_path)
    try:
        resumed = second.resume("obj-ship-cap010")
    finally:
        second.close()
    assert resumed.stored_json == on_disk == original.canonical_json


# -- drift audit -----------------------------------------------------------


def test_drift_audit_flags_violated_constraint_with_pointer(store):
    snap = _sample(store)
    state = {
        "violated_constraints": ["ruff check must pass"],
        "addressed_criteria": [
            "Persist objective snapshots",
            "Run periodic drift audits",
            "Prove exact resume after restart",
        ],
    }
    report = store.audit_drift(state, snap)
    assert isinstance(report, DriftReport)
    assert report.drifted is True
    violations = report.violated_constraints
    assert len(violations) == 1
    assert violations[0].kind == "constraint_violated"
    # Pointer indexes the exact constraint in the snapshot.
    assert violations[0].pointer == "constraints[1]"
    assert snap.constraints[1] == violations[0].detail
    assert report.unaddressed_criteria == ()


def test_drift_audit_flags_unaddressed_criterion_with_pointer(store):
    snap = _sample(store)
    state = {
        "violated_constraints": [],
        "addressed_criteria": ["Persist objective snapshots"],
    }
    report = store.audit_drift(state, snap)
    assert report.drifted is True
    unaddressed = report.unaddressed_criteria
    assert {f.pointer for f in unaddressed} == {
        "acceptance_criteria[1]",
        "acceptance_criteria[2]",
    }
    assert all(f.kind == "criterion_unaddressed" for f in unaddressed)


def test_drift_audit_passes_compliant_state(store):
    snap = _sample(store)
    state = {
        "violated_constraints": [],
        "addressed_criteria": [
            "Persist objective snapshots",
            "Run periodic drift audits",
            "Prove exact resume after restart",
        ],
    }
    report = store.audit_drift(state, snap)
    assert report.drifted is False
    assert report.findings == ()


def test_drift_audit_is_deterministic(store):
    snap = _sample(store)
    state = {"violated_constraints": ["ruff check must pass"], "addressed_criteria": []}
    first = store.audit_drift(state, snap)
    second = store.audit_drift(state, snap)
    assert first == second


# -- revision history append-only ------------------------------------------


def test_revision_history_is_append_only(store):
    snap1 = _sample(store)
    snap2 = store.snapshot(
        "obj-ship-cap010",
        goal="Ship long-horizon task persistence to Level 2",
        constraints=["Do not touch protected files", "ruff check must pass"],
        acceptance_criteria=[
            "Persist objective snapshots",
            "Run periodic drift audits",
            "Prove exact resume after restart",
        ],
        progress={"phase": "verification", "criteria_done": ["Persist objective snapshots"]},
        created_at=1_700_000_500.0,
    )
    assert snap2.revision == 2

    history = store.history("obj-ship-cap010")
    assert [s.revision for s in history] == [1, 2]
    # Prior revision is untouched and still fully recoverable.
    assert history[0] == snap1
    assert history[0].progress == {
        "phase": "implementation",
        "files_written": 1,
        "criteria_done": [],
    }
    assert history[1].progress["phase"] == "verification"
    # Latest reflects the newest revision.
    assert store.latest("obj-ship-cap010") == snap2


def test_resume_reflects_latest_revision(store_path):
    first = ObjectiveStore(path=store_path)
    _sample(first)
    first.snapshot(
        "obj-ship-cap010",
        goal="updated goal",
        progress={"phase": "done"},
        created_at=1_700_001_000.0,
    )
    first.close()

    second = ObjectiveStore(path=store_path)
    try:
        resumed = second.resume("obj-ship-cap010")
    finally:
        second.close()
    assert resumed.revision == 2
    assert resumed.snapshot.goal == "updated goal"
    assert resumed.progress == {"phase": "done"}


# -- empty / missing handling ----------------------------------------------


def test_latest_missing_returns_none(store):
    assert store.latest("nope") is None


def test_history_missing_returns_empty(store):
    assert store.history("nope") == []


def test_resume_missing_raises(store):
    with pytest.raises(ObjectiveNotFoundError):
        store.resume("nope")


def test_snapshot_rejects_empty_id(store):
    with pytest.raises(ValueError):
        store.snapshot("", goal="x")


def test_snapshot_with_no_constraints_or_criteria(store):
    snap = store.snapshot("bare", goal="just a goal")
    assert snap.constraints == ()
    assert snap.acceptance_criteria == ()
    assert snap.progress == {}
    # Empty-objective drift audit is trivially compliant.
    report = store.audit_drift({}, snap)
    assert report.drifted is False
    # Round-trips.
    assert store.latest("bare") == snap


def test_canonical_json_is_stable_and_sorted(store):
    snap = _sample(store)
    payload = json.loads(snap.canonical_json)
    assert list(payload.keys()) == sorted(payload.keys())
    # Re-serialization is idempotent.
    assert snap.canonical_json == ObjectiveSnapshot.from_payload(payload).canonical_json
