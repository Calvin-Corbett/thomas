"""CAP-034 acceptance: cross-vendor agent hosting with a shared scorecard.

Proves the exact acceptance line: "Add external agent runtimes to the roster and
compare them with a shared scorecard." Registers two external runtimes plus an
internal one, runs the shared scorecard over one task set, and asserts every
runtime is scored on identical metrics, the ranking is correct and
deterministic, a failing runtime is scored (not crashed), and adding a runtime
updates the roster.

Everything is hermetic: an injected fake clock supplies latency, an injected
scorer supplies quality, and no network or live model is touched.
"""

import dataclasses

import pytest

from thomas.agent.vendor_roster import (
    ORIGIN_EXTERNAL,
    ORIGIN_INTERNAL,
    AgentRuntime,
    InvocationResult,
    RuntimeInvocationError,
    RuntimeMetrics,
    ScorecardConfig,
    Task,
    VendorRoster,
    unit_scorer,
)


class FakeClock:
    """Monotonic fake clock; adapters advance it to simulate latency."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def __call__(self) -> float:
        return self.now


def _adapter(clock, *, latency, tokens, cost, output="ok", succeeded=True):
    """Build a deterministic invoke adapter that advances the fake clock."""

    def invoke(_task: Task) -> InvocationResult:
        clock.advance(latency)
        return InvocationResult(output=output, tokens=tokens, cost=cost, succeeded=succeeded)

    return invoke


def _failing_adapter(clock, *, latency=0.5):
    def invoke(_task: Task) -> InvocationResult:
        clock.advance(latency)
        raise RuntimeInvocationError("vendor endpoint exploded")

    return invoke


def _task_set():
    return [
        Task(task_id="t1", prompt="summarize the doc"),
        Task(task_id="t2", prompt="write a test"),
        Task(task_id="t3", prompt="fix the bug"),
    ]


# ---------------------------------------------------------------------------
# Registration: internal + external live in one roster
# ---------------------------------------------------------------------------


def test_register_internal_and_external_runtimes():
    clock = FakeClock()
    roster = VendorRoster(clock=clock)
    roster.register_internal("thomas-loop", invoke=_adapter(clock, latency=1.0, tokens=100, cost=0.0))
    roster.register(
        "anthropic-agent",
        vendor="anthropic",
        invoke=_adapter(clock, latency=1.0, tokens=100, cost=0.01),
        origin=ORIGIN_EXTERNAL,
    )
    roster.register(
        "openai-agent",
        vendor="openai",
        invoke=_adapter(clock, latency=1.0, tokens=100, cost=0.02),
        origin=ORIGIN_EXTERNAL,
    )

    assert len(roster) == 3
    assert roster.names == ("anthropic-agent", "openai-agent", "thomas-loop")
    assert roster.get("thomas-loop").origin == ORIGIN_INTERNAL
    assert roster.get("anthropic-agent").is_external is True
    externals = [r for r in roster.runtimes() if r.is_external]
    assert {r.name for r in externals} == {"anthropic-agent", "openai-agent"}


def test_register_validates_origin_and_adapter():
    roster = VendorRoster(clock=FakeClock())
    with pytest.raises(ValueError):
        roster.register("bad", vendor="x", invoke=lambda t: InvocationResult(), origin="sideways")
    with pytest.raises(ValueError):
        roster.register("", vendor="x", invoke=lambda t: InvocationResult())
    with pytest.raises(TypeError):
        roster.register("nope", vendor="x", invoke="not-callable")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Shared scorecard: identical metrics for every runtime
# ---------------------------------------------------------------------------


def test_shared_scorecard_scores_every_runtime_on_identical_metrics():
    clock = FakeClock()
    roster = VendorRoster(clock=clock)
    roster.register_internal("thomas-loop", invoke=_adapter(clock, latency=1.0, tokens=80, cost=0.0))
    roster.register("anthropic-agent", vendor="anthropic", invoke=_adapter(clock, latency=2.0, tokens=120, cost=0.03))
    roster.register("openai-agent", vendor="openai", invoke=_adapter(clock, latency=3.0, tokens=200, cost=0.05))

    report = roster.run_scorecard(_task_set(), scorer=unit_scorer)

    # Every registered runtime appears exactly once.
    assert set(report.ranking()) == {"thomas-loop", "anthropic-agent", "openai-agent"}
    assert len(report.cards) == 3

    # Identical metric shape for every runtime, computed over the same 3 tasks.
    metric_fields = {f.name for f in dataclasses.fields(RuntimeMetrics)}
    for card in report.cards:
        assert card.metrics.task_count == 3
        assert len(card.task_scores) == 3
        assert {ts.task_id for ts in card.task_scores} == {"t1", "t2", "t3"}
        # Same set of metrics measured for each runtime.
        assert {f.name for f in dataclasses.fields(card.metrics)} == metric_fields
        assert card.metrics.success_rate == 1.0

    # Latency is driven by the injected clock: each runtime's per-task latency
    # is its adapter's advance amount, so avg_latency reflects the injection.
    assert report.card("thomas-loop").metrics.avg_latency == pytest.approx(1.0)
    assert report.card("anthropic-agent").metrics.avg_latency == pytest.approx(2.0)
    assert report.card("openai-agent").metrics.avg_latency == pytest.approx(3.0)
    # Token/cost aggregates identical formula across runtimes.
    assert report.card("openai-agent").metrics.total_tokens == 600
    assert report.card("anthropic-agent").metrics.total_cost == pytest.approx(0.09)


# ---------------------------------------------------------------------------
# Ranking correctness + determinism
# ---------------------------------------------------------------------------


def test_ranking_is_correct_and_deterministic():
    def build():
        clock = FakeClock()
        roster = VendorRoster(clock=clock)
        # "fast-cheap" dominates every lower-is-better metric and ties on
        # success/quality, so it must rank first.
        roster.register_internal("fast-cheap", invoke=_adapter(clock, latency=1.0, tokens=50, cost=0.0))
        roster.register("mid", vendor="v-mid", invoke=_adapter(clock, latency=2.0, tokens=100, cost=0.02))
        roster.register("slow-expensive", vendor="v-slow", invoke=_adapter(clock, latency=4.0, tokens=300, cost=0.10))
        return roster

    report = build().run_scorecard(_task_set(), scorer=unit_scorer)
    assert report.ranking() == ("fast-cheap", "mid", "slow-expensive")
    assert report.winner.name == "fast-cheap"
    assert report.rank_of("slow-expensive") == 3
    # Composite scores strictly ordered.
    comps = [report.card(n).composite for n in report.ranking()]
    assert comps[0] > comps[1] > comps[2]

    # Determinism: rebuilding from scratch and re-running yields the identical
    # ranking and identical composite scores.
    report2 = build().run_scorecard(_task_set(), scorer=unit_scorer)
    assert report2.ranking() == report.ranking()
    for name in report.ranking():
        assert report2.card(name).composite == report.card(name).composite


def test_quality_scorer_can_flip_the_ranking():
    clock = FakeClock()
    roster = VendorRoster(clock=clock)
    # Both identical on cost/latency/tokens; quality (injected scorer) decides.
    roster.register("smart", vendor="a", invoke=_adapter(clock, latency=1.0, tokens=100, cost=0.01, output="great"))
    roster.register("dull", vendor="b", invoke=_adapter(clock, latency=1.0, tokens=100, cost=0.01, output="meh"))

    def scorer(_task, output):
        return 1.0 if output == "great" else 0.2

    report = roster.run_scorecard(_task_set(), scorer=scorer)
    assert report.ranking() == ("smart", "dull")
    assert report.card("smart").metrics.avg_quality == pytest.approx(1.0)
    assert report.card("dull").metrics.avg_quality == pytest.approx(0.2)


def test_ranking_ties_break_by_name():
    clock = FakeClock()
    roster = VendorRoster(clock=clock)
    # Perfectly identical runtimes -> equal composite -> deterministic name order.
    roster.register("zeta", vendor="v", invoke=_adapter(clock, latency=1.0, tokens=100, cost=0.01))
    roster.register("alpha", vendor="v", invoke=_adapter(clock, latency=1.0, tokens=100, cost=0.01))
    report = roster.run_scorecard(_task_set())
    assert report.card("zeta").composite == report.card("alpha").composite
    assert report.ranking() == ("alpha", "zeta")


# ---------------------------------------------------------------------------
# A failing runtime is scored, not crashed
# ---------------------------------------------------------------------------


def test_failing_runtime_is_scored_not_crashed():
    clock = FakeClock()
    roster = VendorRoster(clock=clock)
    roster.register_internal("healthy", invoke=_adapter(clock, latency=1.0, tokens=100, cost=0.0))
    roster.register("broken", vendor="flaky-co", invoke=_failing_adapter(clock, latency=0.5))

    # Does not raise despite the broken runtime.
    report = roster.run_scorecard(_task_set(), scorer=unit_scorer)

    broken = report.card("broken")
    assert broken.metrics.success_rate == 0.0
    assert broken.metrics.avg_quality == 0.0
    assert all(ts.succeeded is False for ts in broken.task_scores)
    assert all(ts.error and "RuntimeInvocationError" in ts.error for ts in broken.task_scores)
    # Latency was still measured from the injected clock.
    assert broken.metrics.avg_latency == pytest.approx(0.5)
    # The healthy runtime is scored normally and outranks the broken one.
    assert report.card("healthy").metrics.success_rate == 1.0
    assert report.ranking()[0] == "healthy"
    assert report.rank_of("broken") == 2


def test_soft_failure_result_is_scored_as_failure():
    clock = FakeClock()
    roster = VendorRoster(clock=clock)
    roster.register("soft-fail", vendor="v", invoke=_adapter(clock, latency=1.0, tokens=10, cost=0.0, succeeded=False))
    report = roster.run_scorecard([Task(task_id="only")], scorer=unit_scorer)
    card = report.card("soft-fail")
    assert card.metrics.success_rate == 0.0
    assert card.task_scores[0].succeeded is False
    assert card.task_scores[0].quality == 0.0


def test_partial_failure_yields_fractional_success_rate():
    clock = FakeClock()
    roster = VendorRoster(clock=clock)
    calls = {"n": 0}

    def flaky(_task):
        calls["n"] += 1
        clock.advance(1.0)
        if calls["n"] == 2:  # fail exactly the second task
            raise RuntimeInvocationError("transient")
        return InvocationResult(output="ok", tokens=100, cost=0.01)

    roster.register("flaky", vendor="v", invoke=flaky)
    report = roster.run_scorecard(_task_set(), scorer=unit_scorer)
    assert report.card("flaky").metrics.success_rate == pytest.approx(2 / 3)


# ---------------------------------------------------------------------------
# Adding a runtime updates the roster
# ---------------------------------------------------------------------------


def test_adding_a_runtime_updates_the_roster_and_scorecard():
    clock = FakeClock()
    roster = VendorRoster(clock=clock)
    roster.register_internal("thomas-loop", invoke=_adapter(clock, latency=1.0, tokens=100, cost=0.0))
    roster.register("anthropic-agent", vendor="anthropic", invoke=_adapter(clock, latency=1.5, tokens=100, cost=0.01))

    report1 = roster.run_scorecard(_task_set())
    assert set(report1.ranking()) == {"thomas-loop", "anthropic-agent"}
    assert len(roster) == 2

    # Add a new external runtime.
    roster.register("gemini-agent", vendor="google", invoke=_adapter(clock, latency=2.0, tokens=100, cost=0.02))
    assert len(roster) == 3
    assert "gemini-agent" in roster
    assert isinstance(roster.get("gemini-agent"), AgentRuntime)

    report2 = roster.run_scorecard(_task_set())
    assert set(report2.ranking()) == {"thomas-loop", "anthropic-agent", "gemini-agent"}


def test_reregister_replaces_and_unregister_removes():
    clock = FakeClock()
    roster = VendorRoster(clock=clock)
    roster.register("agent", vendor="old-vendor", invoke=_adapter(clock, latency=1.0, tokens=100, cost=0.0))
    assert roster.get("agent").vendor == "old-vendor"
    # Re-registering the same name swaps the adapter/vendor, roster stays size 1.
    roster.register("agent", vendor="new-vendor", invoke=_adapter(clock, latency=1.0, tokens=50, cost=0.0))
    assert len(roster) == 1
    assert roster.get("agent").vendor == "new-vendor"
    # Unregister removes it.
    assert roster.unregister("agent") is True
    assert roster.unregister("agent") is False
    assert len(roster) == 0


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


def test_scorecard_requires_tasks_and_runtimes():
    clock = FakeClock()
    empty = VendorRoster(clock=clock)
    with pytest.raises(ValueError):
        empty.run_scorecard(_task_set())
    empty.register("a", vendor="v", invoke=_adapter(clock, latency=1.0, tokens=1, cost=0.0))
    with pytest.raises(ValueError):
        empty.run_scorecard([])


def test_report_to_dict_round_trips_ranking():
    clock = FakeClock()
    roster = VendorRoster(clock=clock)
    roster.register("a", vendor="v", invoke=_adapter(clock, latency=1.0, tokens=100, cost=0.02))
    roster.register("b", vendor="v", invoke=_adapter(clock, latency=1.0, tokens=50, cost=0.01))
    report = roster.run_scorecard(_task_set())
    d = report.to_dict()
    assert d["ranking"] == list(report.ranking())
    assert d["task_ids"] == ["t1", "t2", "t3"]
    assert {c["name"] for c in d["cards"]} == {"a", "b"}
    assert all("metrics" in c and "task_scores" in c for c in d["cards"])


def test_bad_weights_rejected():
    clock = FakeClock()
    roster = VendorRoster(clock=clock)
    roster.register("a", vendor="v", invoke=_adapter(clock, latency=1.0, tokens=1, cost=0.0))
    cfg = ScorecardConfig(
        success_weight=0.0, quality_weight=0.0, latency_weight=0.0, cost_weight=0.0, tokens_weight=0.0
    )
    with pytest.raises(ValueError):
        roster.run_scorecard(_task_set(), config=cfg)
