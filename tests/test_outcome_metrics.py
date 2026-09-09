"""Tests for agent adoption/outcome metrics + counterfactual dashboard (CAP-129).

Acceptance: add agent outcome metrics and a counterfactual productivity
dashboard. Covered here: outcomes recorded per agent (accepted/rejected/time),
the counterfactual delta computed vs an injected baseline (formula asserted),
the dashboard aggregates agents, a zero-activity agent is handled, and outcomes
round-trip through persistence.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from thomas.observability.outcome_metrics import (
    AgentOutcome,
    Baseline,
    CounterfactualEstimate,
    OutcomeMetricsStore,
    ProductivityDashboard,
    counterfactual_from_summary,
    summarize_outcomes,
)


class FakeClock:
    """Deterministic, injectable clock returning preset float timestamps."""

    def __init__(self, values: list[float]) -> None:
        self._values = list(values)
        self._i = 0

    def __call__(self) -> float:
        if self._i < len(self._values):
            v = self._values[self._i]
            self._i += 1
        else:
            v = self._values[-1]
        return v


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "outcomes.sqlite3"


def test_outcomes_recorded_per_agent_accepted_rejected_time(db_path: Path) -> None:
    store = OutcomeMetricsStore(db_path, clock=FakeClock([1000.0]))
    # Agent A: two accepted, one rejected.
    store.record_outcome(agent_id="A", task_id="t1", accepted=True, time_to_complete_s=30.0)
    store.record_outcome(agent_id="A", task_id="t2", accepted=True, time_to_complete_s=50.0)
    store.record_outcome(agent_id="A", task_id="t3", accepted=False, time_to_complete_s=20.0)
    # Agent B: one accepted, unrelated to A.
    store.record_outcome(agent_id="B", task_id="t4", accepted=True, time_to_complete_s=10.0)

    summary = store.agent_summary("A")
    assert summary.agent_id == "A"
    assert summary.tasks_completed == 3
    assert summary.accepted == 2
    assert summary.rejected == 1
    assert summary.total_time_to_complete_s == 100.0
    assert summary.avg_time_to_complete_s == pytest.approx(100.0 / 3)
    assert summary.acceptance_rate == pytest.approx(2 / 3)

    # Per-agent isolation: B's outcome does not leak into A.
    assert store.agent_summary("B").tasks_completed == 1


def test_counterfactual_delta_vs_injected_baseline_formula(db_path: Path) -> None:
    store = OutcomeMetricsStore(db_path, clock=FakeClock([1000.0]))
    # 3 accepted, 1 rejected. Agent spent 40+60+80 on accepted, 25 on rejected.
    store.record_outcome(agent_id="A", task_id="t1", accepted=True, time_to_complete_s=40.0, human_edits_after=1)
    store.record_outcome(agent_id="A", task_id="t2", accepted=True, time_to_complete_s=60.0, human_edits_after=0)
    store.record_outcome(agent_id="A", task_id="t3", accepted=True, time_to_complete_s=80.0, human_edits_after=2)
    store.record_outcome(agent_id="A", task_id="t4", accepted=False, time_to_complete_s=25.0, human_edits_after=0)

    baseline = Baseline(human_seconds_per_task=200.0, seconds_per_human_edit=15.0)
    summary = store.agent_summary("A")
    est = counterfactual_from_summary(summary, baseline)

    # baseline credit only for accepted work: 200 * 3 = 600
    assert est.baseline_cost_s == pytest.approx(600.0)
    # agent active time over ALL outcomes (accepted + rejected): 40+60+80+25 = 205
    assert est.agent_active_s == pytest.approx(205.0)
    # rework: 15 * total human edits (1+0+2 = 3) = 45
    assert est.rework_cost_s == pytest.approx(45.0)
    # effective = active + rework = 250
    assert est.agent_effective_s == pytest.approx(250.0)
    # delta = baseline - effective = 600 - 250 = 350 (net time saved)
    assert est.delta_s == pytest.approx(350.0)


def test_dashboard_aggregates_agents(db_path: Path) -> None:
    store = OutcomeMetricsStore(db_path, clock=FakeClock([1000.0]))
    store.record_outcome(agent_id="A", task_id="t1", accepted=True, time_to_complete_s=40.0)
    store.record_outcome(agent_id="A", task_id="t2", accepted=False, time_to_complete_s=10.0)
    store.record_outcome(agent_id="B", task_id="t3", accepted=True, time_to_complete_s=100.0)

    baseline = Baseline(human_seconds_per_task=120.0)
    dash = store.build_dashboard(baseline)
    assert isinstance(dash, ProductivityDashboard)

    # One row per agent, sorted by agent id.
    assert [row.summary.agent_id for row in dash.agents] == ["A", "B"]

    # A: baseline 120*1=120, active=50, delta=70. B: 120*1=120, active=100, delta=20.
    row_a = dash.row_for("A")
    row_b = dash.row_for("B")
    assert row_a is not None and row_b is not None
    assert row_a.counterfactual.delta_s == pytest.approx(70.0)
    assert row_b.counterfactual.delta_s == pytest.approx(20.0)

    # Aggregate is the element-wise sum across agents.
    assert dash.aggregate.baseline_cost_s == pytest.approx(240.0)
    assert dash.aggregate.agent_active_s == pytest.approx(150.0)
    assert dash.aggregate.delta_s == pytest.approx(90.0)
    assert dash.aggregate.delta_s == pytest.approx(row_a.counterfactual.delta_s + row_b.counterfactual.delta_s)

    # Task tallies roll up too.
    assert dash.total_tasks == 3
    assert dash.total_accepted == 2
    assert dash.total_rejected == 1


def test_zero_activity_agent_handled(db_path: Path) -> None:
    store = OutcomeMetricsStore(db_path, clock=FakeClock([1000.0]))
    store.record_outcome(agent_id="A", task_id="t1", accepted=True, time_to_complete_s=40.0)

    # Summary for an agent with no recorded outcomes is all zeros, not an error.
    idle = store.agent_summary("ghost")
    assert idle.agent_id == "ghost"
    assert idle.tasks_completed == 0
    assert idle.accepted == 0
    assert idle.rejected == 0
    assert idle.avg_time_to_complete_s == 0.0
    assert idle.acceptance_rate == 0.0

    baseline = Baseline(human_seconds_per_task=100.0, seconds_per_human_edit=5.0)
    assert counterfactual_from_summary(idle, baseline) == CounterfactualEstimate.zero()

    # A zero-activity agent named explicitly still appears on the dashboard.
    dash = store.build_dashboard(baseline, agent_ids=["ghost"])
    ghost_row = dash.row_for("ghost")
    assert ghost_row is not None
    assert ghost_row.summary.tasks_completed == 0
    assert ghost_row.counterfactual.delta_s == 0.0
    # And it contributes nothing to the aggregate delta (only A does).
    assert dash.aggregate.delta_s == pytest.approx(dash.row_for("A").counterfactual.delta_s)


def test_round_trip_persistence(db_path: Path) -> None:
    store = OutcomeMetricsStore(db_path, clock=FakeClock([2000.0]))
    oid = store.record(
        AgentOutcome(
            agent_id="A",
            task_id="t1",
            accepted=True,
            time_to_complete_s=42.5,
            human_edits_after=3,
            period="2026-07",
        )
    )
    store.record_outcome(agent_id="A", task_id="t2", accepted=False, time_to_complete_s=12.0, period="2026-07")

    # A brand-new store on the same path sees the previously recorded outcomes.
    reopened = OutcomeMetricsStore(db_path, clock=FakeClock([9999.0]))
    outcomes = reopened.query_by_agent("A")
    assert len(outcomes) == 2
    first = next(o for o in outcomes if o.outcome_id == oid)
    assert first.agent_id == "A"
    assert first.task_id == "t1"
    assert first.accepted is True
    assert first.time_to_complete_s == 42.5
    assert first.human_edits_after == 3
    assert first.period == "2026-07"
    assert first.recorded_at == 2000.0  # clock-stamped at record time, survives reopen

    # Period filtering round-trips too.
    assert len(reopened.query_by_period("2026-07")) == 2
    assert reopened.query_by_agent("A", period="2026-99") == []


def test_summarize_outcomes_pure_helper() -> None:
    # The pure fold matches the store path and handles the empty case.
    assert summarize_outcomes("A", []).tasks_completed == 0
    outcomes = [
        AgentOutcome(agent_id="A", task_id="t1", accepted=True, time_to_complete_s=10.0),
        AgentOutcome(agent_id="A", task_id="t2", accepted=False, time_to_complete_s=30.0),
    ]
    summary = summarize_outcomes("A", outcomes)
    assert summary.accepted == 1
    assert summary.rejected == 1
    assert summary.total_time_to_complete_s == 40.0
    assert summary.acceptance_rate == pytest.approx(0.5)
