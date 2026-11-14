"""The ledger advances on a verdict, never on a claim.

There is deliberately no API for marking a step done. The only way forward is
``attempt``, which evaluates the open step's gates. An agent that has forgotten
the rules, or decided it is finished, has nothing to call.
"""

from __future__ import annotations

from thomas.work.lanes.gates import GateContext
from thomas.work.lanes.ledger import PARK, WAIVE, RunLedger
from thomas.work.lanes.model import Gate, Lane, Step


def _lane() -> Lane:
    proof = {"observed_at": "2026-09-08T00:00:00Z", "reason": "seen failing"}
    return Lane(
        id="two-step",
        job_kind="test",
        version=1,
        steps=[
            Step(
                id="discover",
                name="Discover",
                gates=[
                    Gate(
                        id="goal",
                        kind="mechanical",
                        description="a real goal",
                        check="nonempty_text",
                        params={"field": "goal", "min_chars": 10},
                        red_proof=proof,
                    )
                ],
            ),
            Step(
                id="deliver",
                name="Deliver",
                gates=[
                    Gate(
                        id="artifact",
                        kind="evidence",
                        description="something to show",
                        check="report",
                        params={"artifact": "report", "min_bytes": 20},
                        red_proof=proof,
                    )
                ],
            ),
        ],
    )


def test_the_ledger_has_no_way_to_declare_a_step_done():
    ledger = RunLedger(lane=_lane(), autonomy_level=3, run_id="r1")
    for forbidden in ("mark_done", "complete_step", "set_passed", "skip"):
        assert not hasattr(ledger, forbidden), f"{forbidden} would be a door around the gate"


def test_a_failing_gate_leaves_the_step_open():
    ledger = RunLedger(lane=_lane(), autonomy_level=3, run_id="r1")
    outcome = ledger.attempt(GateContext(fields={"goal": "hm"}))
    assert outcome.advanced is False
    assert ledger.open_step().id == "discover"
    assert "needs at least 10" in outcome.failures[0]


def test_the_second_step_is_unreachable_until_the_first_passes():
    ledger = RunLedger(lane=_lane(), autonomy_level=3, run_id="r1")
    ledger.attempt(GateContext(fields={"goal": "hm"}))
    assert ledger.open_step().id == "discover", "still on step one"
    ledger.attempt(GateContext(fields={"goal": "reconcile the driver manifests"}))
    assert ledger.open_step().id == "deliver", "only now does step two open"


def test_the_open_gate_is_restated_every_turn():
    """Long context cannot erode what is re-presented on each turn."""
    ledger = RunLedger(lane=_lane(), autonomy_level=3, run_id="r1")
    first = ledger.current_brief()
    for _ in range(50):
        ledger.attempt(GateContext(fields={"goal": ""}))
    assert ledger.current_brief() == first, "the brief is regenerated, not remembered"
    assert "a real goal" in first


def test_completion_is_refused_while_any_step_is_unresolved():
    ledger = RunLedger(lane=_lane(), autonomy_level=3, run_id="r1")
    ledger.attempt(GateContext(fields={"goal": "reconcile the driver manifests"}))
    verdict = ledger.completion_verdict()
    assert verdict.passed is False
    assert "deliver" in verdict.reason


def test_an_agent_run_parks_when_a_gate_survives_its_retries():
    """L3's own directive says to stop when genuinely blocked."""
    ledger = RunLedger(lane=_lane(), autonomy_level=3, run_id="r1", attempts_per_step=2)
    for _ in range(3):
        ledger.attempt(GateContext(fields={"goal": ""}))
    assert ledger.resolve_block(user_present=False) == PARK
    assert ledger.open_step().id == "discover"


def test_full_autonomy_without_presence_waives_and_records_rather_than_stalling():
    """L4 says keep momentum -- but the waiver is written down, never silent."""
    ledger = RunLedger(lane=_lane(), autonomy_level=4, run_id="r1", attempts_per_step=2)
    for _ in range(3):
        ledger.attempt(GateContext(fields={"goal": ""}))
    assert ledger.resolve_block(user_present=False) == WAIVE
    assert ledger.open_step().id == "deliver", "the run keeps moving"
    assert [w["step_id"] for w in ledger.waivers] == ["discover"]


def test_a_run_carrying_a_waiver_can_never_report_clean():
    ledger = RunLedger(lane=_lane(), autonomy_level=4, run_id="r1", attempts_per_step=1)
    ledger.attempt(GateContext(fields={"goal": ""}))
    ledger.resolve_block(user_present=False)
    ledger.attempt(GateContext(artifacts={"report": 400}))
    verdict = ledger.completion_verdict()
    assert verdict.passed is True, "the run finished"
    assert verdict.clean is False, "but it is not clean"
    assert "1 step waived" in ledger.report_headline()


def test_full_autonomy_asks_for_the_tap_first_when_someone_is_there():
    """L4's directive prefers native auth over stopping -- but a human is better than a waiver."""
    ledger = RunLedger(lane=_lane(), autonomy_level=4, run_id="r1", attempts_per_step=1)
    ledger.attempt(GateContext(fields={"goal": ""}))
    assert ledger.resolve_block(user_present=True) == PARK
