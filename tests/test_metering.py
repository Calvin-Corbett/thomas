"""Tests for thomas.core.metering.MeteringEngine (CAP-128).

Every test is hermetic: a temp JSON path and an injected, mutable clock. No
network, no live model, no wall-clock dependence.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from thomas.core.metering import (
    GLOBAL_SCOPE,
    MeteringEngine,
)

PERIOD_START = datetime(2026, 1, 1, 0, 0, 0)
PERIOD = timedelta(days=30)


class _Clock:
    """Deterministic, advanceable clock."""

    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def set(self, now: datetime) -> None:
        self.now = now


def _engine(tmp_path, clock, **kw) -> MeteringEngine:
    return MeteringEngine(
        path=tmp_path / "metering.json",
        clock=clock,
        period_start=PERIOD_START,
        period_length=PERIOD,
        **kw,
    )


# ---------------------------------------------------------------------------
# (1) Per-agent attribution: correct and isolated
# ---------------------------------------------------------------------------


def test_per_agent_attribution_is_isolated(tmp_path):
    clock = _Clock(PERIOD_START + timedelta(days=15))
    eng = _engine(tmp_path, clock)

    eng.record_spend("agent-a", tokens=1000, cost=5.0)
    eng.record_spend("agent-a", tokens=500, cost=2.5)
    eng.record_spend("agent-b", tokens=200, cost=1.0)

    assert eng.agent_spend("agent-a") == pytest.approx(7.5)
    assert eng.agent_tokens("agent-a") == 1500
    assert eng.agent_spend("agent-b") == pytest.approx(1.0)
    assert eng.agent_tokens("agent-b") == 200
    # An untouched agent has zero spend, proving isolation.
    assert eng.agent_spend("agent-c") == 0.0
    assert eng.agent_ids() == ["agent-a", "agent-b"]


def test_negative_inputs_are_clamped(tmp_path):
    clock = _Clock(PERIOD_START + timedelta(days=1))
    eng = _engine(tmp_path, clock)
    eng.record_spend("a", tokens=-100, cost=-9.0)
    assert eng.agent_spend("a") == 0.0
    assert eng.agent_tokens("a") == 0


# ---------------------------------------------------------------------------
# (2) Projection: linear extrapolation from a partial period
# ---------------------------------------------------------------------------


def test_projection_formula_on_known_inputs(tmp_path):
    # 6 of 30 days elapsed -> elapsed_fraction = 0.2.
    clock = _Clock(PERIOD_START + timedelta(days=6))
    eng = _engine(tmp_path, clock)
    eng.record_spend("agent-a", tokens=1000, cost=20.0)

    proj = eng.project("agent-a")
    assert proj.elapsed_fraction == pytest.approx(0.2)
    # projected = actual / elapsed_fraction = 20 / 0.2 = 100.
    assert proj.projected_spend == pytest.approx(100.0)
    assert proj.actual_spend == pytest.approx(20.0)
    assert proj.period_start == PERIOD_START.isoformat()
    assert proj.period_end == (PERIOD_START + PERIOD).isoformat()


def test_projection_caps_fraction_at_full_period(tmp_path):
    # Past the end of the period: fraction caps at 1.0, projected == actual.
    clock = _Clock(PERIOD_START + timedelta(days=60))
    eng = _engine(tmp_path, clock)
    eng.record_spend("agent-a", tokens=1, cost=42.0)
    proj = eng.project("agent-a")
    assert proj.elapsed_fraction == pytest.approx(1.0)
    assert proj.projected_spend == pytest.approx(42.0)


def test_global_projection_aggregates_agents(tmp_path):
    clock = _Clock(PERIOD_START + timedelta(days=6))  # fraction 0.2
    eng = _engine(tmp_path, clock)
    eng.record_spend("a", tokens=1, cost=4.0)
    eng.record_spend("b", tokens=1, cost=6.0)
    proj = eng.project(None)
    assert proj.scope == "global"
    assert proj.agent_id == GLOBAL_SCOPE
    assert proj.actual_spend == pytest.approx(10.0)
    assert proj.projected_spend == pytest.approx(50.0)  # 10 / 0.2


# ---------------------------------------------------------------------------
# (3) Budgets + alerts: 80% warning, 100% breach
# ---------------------------------------------------------------------------


def test_crossing_80_percent_emits_warning(tmp_path):
    # Clock at period end so elapsed_fraction == 1.0 and projected == actual;
    # this isolates the actual-basis crossing under test.
    clock = _Clock(PERIOD_START + PERIOD)
    eng = _engine(tmp_path, clock)
    eng.set_budget("agent-a", 100.0)

    # 79% -> no alert yet.
    assert eng.record_spend("agent-a", tokens=1, cost=79.0) == []

    # cross to 80% -> warning (on both actual and projected bases, dedup by key).
    alerts = eng.record_spend("agent-a", tokens=1, cost=1.0)  # now 80.0
    warnings = [a for a in alerts if a.kind == "warning"]
    assert warnings, alerts
    w = next(a for a in warnings if a.basis == "actual")
    assert w.scope == "agent"
    assert w.agent_id == "agent-a"
    assert w.threshold == pytest.approx(0.8)
    assert w.ratio == pytest.approx(0.8)
    assert all(a.kind == "warning" for a in alerts)  # no breach yet


def test_crossing_100_percent_emits_breach(tmp_path):
    clock = _Clock(PERIOD_START + PERIOD)
    eng = _engine(tmp_path, clock)
    eng.set_budget("agent-a", 100.0)

    eng.record_spend("agent-a", tokens=1, cost=80.0)  # warning fires here
    alerts = eng.record_spend("agent-a", tokens=1, cost=25.0)  # now 105 -> breach

    breaches = [a for a in alerts if a.kind == "breach"]
    assert breaches, alerts
    b = next(a for a in breaches if a.basis == "actual")
    assert b.threshold == pytest.approx(1.0)
    assert b.ratio == pytest.approx(1.05)
    # The 80% warning already fired and is not repeated.
    assert not any(a.kind == "warning" and a.basis == "actual" for a in alerts)


def test_projected_basis_can_trip_alert_before_actual(tmp_path):
    # Only 20% of the period elapsed; a small actual spend projects over budget.
    clock = _Clock(PERIOD_START + timedelta(days=6))  # fraction 0.2
    eng = _engine(tmp_path, clock)
    eng.set_budget("agent-a", 100.0)

    # actual = 30 (30% of budget, below 80%) but projected = 150 (breach).
    alerts = eng.record_spend("agent-a", tokens=1, cost=30.0)
    projected = [a for a in alerts if a.basis == "projected"]
    assert any(a.kind == "warning" for a in projected)
    assert any(a.kind == "breach" for a in projected)
    # No actual-basis alert, since actual is only 30%.
    assert not any(a.basis == "actual" for a in alerts)


def test_alerts_isolated_between_agents(tmp_path):
    clock = _Clock(PERIOD_START + PERIOD)
    eng = _engine(tmp_path, clock)
    eng.set_budget("agent-a", 100.0)
    eng.set_budget("agent-b", 100.0)

    alerts = eng.record_spend("agent-a", tokens=1, cost=90.0)
    assert alerts  # agent-a warns
    assert all(a.agent_id == "agent-a" for a in alerts)


# ---------------------------------------------------------------------------
# (4) Policy-driven downshift
# ---------------------------------------------------------------------------


def test_over_budget_agent_downshifts_under_budget_does_not(tmp_path):
    clock = _Clock(PERIOD_START + PERIOD)  # fraction 1.0, projected == actual
    eng = _engine(tmp_path, clock)
    eng.set_budget("hot", 100.0)
    eng.set_budget("cool", 100.0)

    eng.record_spend("hot", tokens=1, cost=120.0)  # 120% -> over
    eng.record_spend("cool", tokens=1, cost=40.0)  # 40% -> under

    hot = eng.downshift_decision("hot")
    cool = eng.downshift_decision("cool")

    assert hot.downshift is True
    assert hot.current_tier == "premium"
    assert hot.recommended_tier == "standard"
    assert hot.basis == "actual"
    assert "downshift premium -> standard" in hot.reason

    assert cool.downshift is False
    assert cool.recommended_tier == cool.current_tier
    assert cool.basis == ""


def test_downshift_on_projection_before_actual_overage(tmp_path):
    clock = _Clock(PERIOD_START + timedelta(days=6))  # fraction 0.2
    eng = _engine(tmp_path, clock)
    eng.set_budget("agent-a", 100.0)
    # actual 30 (under) but projected 150 (over) -> downshift on projected basis.
    eng.record_spend("agent-a", tokens=1, cost=30.0)
    decision = eng.downshift_decision("agent-a")
    assert decision.downshift is True
    assert decision.basis == "projected"


def test_downshift_walks_the_tier_ladder_and_floors(tmp_path):
    clock = _Clock(PERIOD_START + PERIOD)
    eng = _engine(tmp_path, clock)
    eng.set_budget("agent-a", 100.0)
    eng.set_tier("agent-a", "economy")  # already cheapest
    eng.record_spend("agent-a", tokens=1, cost=200.0)
    decision = eng.downshift_decision("agent-a")
    assert decision.downshift is True
    assert decision.current_tier == "economy"
    assert decision.recommended_tier == "economy"  # cannot go cheaper


def test_no_budget_means_no_downshift(tmp_path):
    clock = _Clock(PERIOD_START + PERIOD)
    eng = _engine(tmp_path, clock)
    eng.record_spend("agent-a", tokens=1, cost=999.0)
    decision = eng.downshift_decision("agent-a")
    assert decision.downshift is False
    assert "no budget" in decision.reason


# ---------------------------------------------------------------------------
# Global budget aggregation
# ---------------------------------------------------------------------------


def test_global_budget_aggregates_agents(tmp_path):
    clock = _Clock(PERIOD_START + PERIOD)  # fraction 1.0
    eng = _engine(tmp_path, clock)
    eng.set_global_budget(100.0)

    eng.record_spend("a", tokens=1, cost=50.0)
    alerts = eng.record_spend("b", tokens=1, cost=55.0)  # aggregate 105 -> breach

    assert eng.global_spend() == pytest.approx(105.0)
    global_breach = [a for a in alerts if a.scope == "global" and a.kind == "breach"]
    assert global_breach
    assert global_breach[0].agent_id == GLOBAL_SCOPE
    assert global_breach[0].ratio == pytest.approx(1.05)


# ---------------------------------------------------------------------------
# Round-trip persistence
# ---------------------------------------------------------------------------


def test_round_trip_persists_all_state(tmp_path):
    clock = _Clock(PERIOD_START + timedelta(days=6))
    path = tmp_path / "metering.json"
    eng = MeteringEngine(
        path=path,
        clock=clock,
        period_start=PERIOD_START,
        period_length=PERIOD,
    )
    eng.set_budget("agent-a", 50.0)
    eng.set_global_budget(200.0)
    eng.set_tier("agent-a", "standard")
    eng.record_spend("agent-a", tokens=1234, cost=12.5)
    eng.record_spend("agent-b", tokens=10, cost=1.0)
    # Trip a durable alert so its dedup key round-trips too.
    first_alerts = eng.active_alerts()

    # Reload from disk with a fresh engine instance.
    eng2 = MeteringEngine(path=path, clock=clock)

    assert eng2.agent_spend("agent-a") == pytest.approx(12.5)
    assert eng2.agent_tokens("agent-a") == 1234
    assert eng2.agent_spend("agent-b") == pytest.approx(1.0)
    assert eng2.global_spend() == pytest.approx(13.5)
    # Budgets, tiers, period, and projection survive the round trip.
    assert eng2.project("agent-a").elapsed_fraction == pytest.approx(0.2)
    d = eng2.downshift_decision("agent-a")
    assert d.current_tier == "standard"

    # Fired-alert dedup persisted: re-recording zero cost yields no repeat alerts.
    assert first_alerts  # sanity: something did fire on agent-a's projection
    repeat = eng2.record_spend("agent-a", tokens=0, cost=0.0)
    assert repeat == []


def test_missing_file_starts_empty(tmp_path):
    clock = _Clock(PERIOD_START)
    eng = MeteringEngine(path=tmp_path / "does_not_exist.json", clock=clock)
    assert eng.agent_ids() == []
    assert eng.global_spend() == 0.0
