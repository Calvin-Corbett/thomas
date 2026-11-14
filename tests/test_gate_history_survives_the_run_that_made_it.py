"""A proposal needs history, and history needs somewhere to live.

`propose_from_lane` reads `gate.checked_count` and `gate.fired_count`, but a lane
is rebuilt on every run, so those counters died with the run that produced them
and no proposal could ever reach its threshold. Counters live here instead --
deliberately NOT in the lane definition, because saving the lane on every run
would push a new version and a history entry each time, and a version number
would stop meaning "someone changed the gates".
"""

from __future__ import annotations

from thomas.work.lanes.model import Gate, Lane, Step
from thomas.work.lanes.proposals import MIN_CHECKS_BEFORE_RETIREMENT, GateProposalStore
from thomas.work.lanes.stats import GateStatsStore, close_run


def _gate(gate_id: str, field: str = "goal") -> Gate:
    return Gate(
        id=gate_id,
        kind="mechanical",
        description=f"{gate_id} holds",
        check="nonempty_text",
        params={"field": field, "min_chars": 5},
        counterexample={"fields": {field: ""}},
    )


def _lane() -> Lane:
    return Lane(id="job", job_kind="job", version=1, steps=[Step(id="s", name="S", gates=[_gate("quiet"), _gate("loud", "other")])])


def _stores(tmp_path):
    return GateStatsStore(path=tmp_path / "stats.json"), GateProposalStore(path=tmp_path / "proposals.json")


def test_counters_accumulate_across_runs(tmp_path):
    stats, proposals = _stores(tmp_path)
    for _ in range(3):
        lane = _lane()
        lane.steps[0].gates[0].checked_count = 1
        lane.steps[0].gates[1].checked_count = 1
        lane.steps[0].gates[1].fired_count = 1
        close_run(lane, waived_gate_ids=[], stats_store=stats, proposal_store=proposals)
    hydrated = stats.hydrate(_lane())
    assert hydrated.steps[0].gates[0].checked_count == 3
    assert hydrated.steps[0].gates[1].fired_count == 3


def test_a_run_that_produced_nothing_does_not_invent_history(tmp_path):
    stats, proposals = _stores(tmp_path)
    close_run(_lane(), waived_gate_ids=[], stats_store=stats, proposal_store=proposals)
    assert stats.hydrate(_lane()).steps[0].gates[0].checked_count == 0


def test_a_quiet_gate_reaches_its_proposal_only_after_enough_runs(tmp_path):
    stats, proposals = _stores(tmp_path)
    queued = []
    for _ in range(MIN_CHECKS_BEFORE_RETIREMENT):
        lane = _lane()
        for gate in lane.steps[0].gates:
            gate.checked_count = 1
        lane.steps[0].gates[1].fired_count = 1  # 'loud' keeps earning its place
        queued = close_run(lane, waived_gate_ids=[], stats_store=stats, proposal_store=proposals)
    assert [p.gate_id for p in proposals.pending("job")] == ["quiet"]
    assert queued and queued[0].evidence["checked_count"] == MIN_CHECKS_BEFORE_RETIREMENT


def test_nothing_is_proposed_before_the_evidence_exists(tmp_path):
    stats, proposals = _stores(tmp_path)
    for _ in range(MIN_CHECKS_BEFORE_RETIREMENT - 1):
        lane = _lane()
        for gate in lane.steps[0].gates:
            gate.checked_count = 1
        close_run(lane, waived_gate_ids=[], stats_store=stats, proposal_store=proposals)
    assert proposals.pending("job") == [], "one run short is still no evidence"


def test_repeated_waivers_accumulate_and_produce_one_ask(tmp_path):
    stats, proposals = _stores(tmp_path)
    for _ in range(3):
        close_run(_lane(), waived_gate_ids=["loud"], stats_store=stats, proposal_store=proposals)
    pending = proposals.pending("job")
    assert [p.gate_id for p in pending] == ["loud"]
    assert pending[0].evidence["waived_count"] == 3


def test_the_boundary_never_raises_into_the_run_it_closes(tmp_path):
    """Bookkeeping must not be able to fail a job that already finished."""
    stats, _ = _stores(tmp_path)
    broken = GateProposalStore(path=tmp_path / "nested" / "cannot" / "exist.json")
    broken.queue = lambda proposals: (_ for _ in ()).throw(OSError("disk gone"))
    assert close_run(_lane(), waived_gate_ids=[], stats_store=stats, proposal_store=broken) == []
