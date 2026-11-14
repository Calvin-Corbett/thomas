"""Thomas may notice a better gate. It may not change its own gates quietly.

Evolution is the point -- gates start imperfect -- but a system that can rewrite
its own checks without asking has no checks. So a change is a *proposal*: it
carries the evidence that produced it, it waits, and applying it needs a real
human authorization. Rejections are remembered, or the same suggestion returns
every run until it is approved out of fatigue.
"""

from __future__ import annotations

import pytest

from thomas.work.lanes.model import Gate, Lane, LaneInvalid, Step
from thomas.work.lanes.proposals import (
    MIN_CHECKS_BEFORE_RETIREMENT,
    GateProposal,
    GateProposalStore,
    apply_proposal,
    propose_from_lane,
)
from thomas.work.lanes.proving import GateCannotFail
from thomas.work.lanes.store import LaneStore


def _gate(gate_id: str, *, checked: int = 0, fired: int = 0, field: str = "goal") -> Gate:
    return Gate(
        id=gate_id,
        kind="mechanical",
        description=f"{gate_id} holds",
        check="nonempty_text",
        params={"field": field, "min_chars": 5},
        counterexample={"fields": {field: ""}},
        checked_count=checked,
        fired_count=fired,
    )


def _lane(*gates: Gate) -> Lane:
    return Lane(id="job", job_kind="job", version=1, steps=[Step(id="s", name="S", gates=list(gates))])


def _granted(**_):
    return True, "authorized"


def _refused(**_):
    return False, "no human authorization"


# ── what produces a proposal ──────────────────────────────────────────────────


def test_a_gate_that_has_never_fired_is_proposed_for_retirement():
    lane = _lane(_gate("never-fires", checked=MIN_CHECKS_BEFORE_RETIREMENT, fired=0), _gate("useful", checked=9, fired=3))
    proposals = propose_from_lane(lane, waived_gate_ids=[])
    assert [p.gate_id for p in proposals] == ["never-fires"]
    assert proposals[0].kind == "retire"
    assert proposals[0].evidence["checked_count"] == MIN_CHECKS_BEFORE_RETIREMENT
    assert "never" in proposals[0].rationale.lower()


def test_a_young_gate_is_left_alone():
    """One quiet run is not evidence. Retiring on it would delete real gates."""
    lane = _lane(_gate("young", checked=2, fired=0))
    assert propose_from_lane(lane, waived_gate_ids=[]) == []


def test_a_gate_that_keeps_being_waived_is_proposed_for_retirement():
    """A gate the user keeps overriding is a wrong gate, not a disobedient user."""
    lane = _lane(_gate("annoying", checked=10, fired=8))
    proposals = propose_from_lane(lane, waived_gate_ids=["annoying", "annoying", "annoying"])
    assert proposals[0].gate_id == "annoying"
    assert proposals[0].evidence["waived_count"] == 3
    assert "waiv" in proposals[0].rationale.lower()


def test_a_healthy_gate_is_never_proposed():
    lane = _lane(_gate("healthy", checked=20, fired=4))
    assert propose_from_lane(lane, waived_gate_ids=[]) == []


# ── the queue behaves ─────────────────────────────────────────────────────────


def test_the_same_proposal_is_not_queued_twice(tmp_path):
    store = GateProposalStore(path=tmp_path / "proposals.json")
    lane = _lane(_gate("never-fires", checked=MIN_CHECKS_BEFORE_RETIREMENT, fired=0))
    first = store.queue(propose_from_lane(lane, waived_gate_ids=[]))
    second = store.queue(propose_from_lane(lane, waived_gate_ids=[]))
    assert len(first) == 1 and second == []
    assert len(store.pending("job")) == 1


def test_a_rejected_proposal_does_not_come_back_on_the_same_evidence(tmp_path):
    store = GateProposalStore(path=tmp_path / "proposals.json")
    lane = _lane(_gate("never-fires", checked=MIN_CHECKS_BEFORE_RETIREMENT, fired=0))
    queued = store.queue(propose_from_lane(lane, waived_gate_ids=[]))
    store.reject(queued[0].id, reason="I want that check")
    assert store.pending("job") == []
    assert store.queue(propose_from_lane(lane, waived_gate_ids=[])) == []


def test_a_rejected_proposal_returns_once_the_evidence_has_doubled(tmp_path):
    store = GateProposalStore(path=tmp_path / "proposals.json")
    lane = _lane(_gate("never-fires", checked=MIN_CHECKS_BEFORE_RETIREMENT, fired=0))
    store.reject(store.queue(propose_from_lane(lane, waived_gate_ids=[]))[0].id, reason="keep it")
    louder = _lane(_gate("never-fires", checked=MIN_CHECKS_BEFORE_RETIREMENT * 2, fired=0))
    assert len(store.queue(propose_from_lane(louder, waived_gate_ids=[]))) == 1


# ── applying one ──────────────────────────────────────────────────────────────


def _stored(tmp_path, *gates: Gate) -> LaneStore:
    lane_store = LaneStore(path=tmp_path / "work_lanes.json")
    lane_store.save_lane(_lane(*gates))
    return lane_store


def test_an_unauthorized_approval_changes_nothing(tmp_path):
    lane_store = _stored(tmp_path, _gate("a"), _gate("b", field="other"))
    proposal = GateProposal(id="p1", job_kind="job", kind="retire", gate_id="b", rationale="never fired", evidence={})
    with pytest.raises(PermissionError, match="no human authorization"):
        apply_proposal(proposal, lane_store, authorize=_refused)
    assert len(lane_store.load_lane("job").steps[0].gates) == 2, "the lane is untouched"


def test_an_approved_retirement_removes_the_gate_and_keeps_the_old_version(tmp_path):
    lane_store = _stored(tmp_path, _gate("a"), _gate("b", field="other"))
    proposal = GateProposal(id="p1", job_kind="job", kind="retire", gate_id="b", rationale="never fired", evidence={})
    updated = apply_proposal(proposal, lane_store, authorize=_granted)
    assert [g.id for g in updated.steps[0].gates] == ["a"]
    assert updated.version == 2
    restored = lane_store.rollback("job")
    assert [g.id for g in restored.steps[0].gates] == ["a", "b"], "a wrong change is reversible"


def test_retiring_the_last_real_gate_is_refused(tmp_path):
    """A lane cannot be emptied one approval at a time."""
    lane_store = _stored(tmp_path, _gate("only"))
    proposal = GateProposal(id="p1", job_kind="job", kind="retire", gate_id="only", rationale="quiet", evidence={})
    with pytest.raises(LaneInvalid, match="mechanical or evidence"):
        apply_proposal(proposal, lane_store, authorize=_granted)


def test_an_added_gate_that_cannot_fail_is_refused_even_when_approved(tmp_path):
    """Human approval does not exempt a new gate from the red-proof rule."""
    lane_store = _stored(tmp_path, _gate("a"))
    broken = Gate(
        id="always-true",
        kind="mechanical",
        description="x",
        check="nonempty_text",
        params={"field": "goal", "min_chars": 1},
        counterexample={"fields": {"goal": "not actually empty"}},
    )
    proposal = GateProposal(
        id="p2", job_kind="job", kind="add", gate_id="always-true", rationale="observed", evidence={}, gate=broken
    )
    with pytest.raises(GateCannotFail):
        apply_proposal(proposal, lane_store, authorize=_granted)


def test_applying_marks_the_proposal_decided(tmp_path):
    store = GateProposalStore(path=tmp_path / "proposals.json")
    lane = _lane(_gate("never-fires", checked=MIN_CHECKS_BEFORE_RETIREMENT, fired=0), _gate("keep", field="other"))
    queued = store.queue(propose_from_lane(lane, waived_gate_ids=[]))[0]
    store.approve(queued.id, approved_by="calvin")
    assert store.pending("job") == []
    assert store.decided("job")[0].status == "approved"
