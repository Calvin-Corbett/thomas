"""Tests for the benchmarked per-task fast inference tier (CAP-096).

Every test is hermetic: an injected ManualClock supplies deterministic latency
measurement, and injected runners/scorers stand in for any live model.
"""

from __future__ import annotations

import pytest

from thomas.models.fast_tier import (
    FAST,
    REASON_FAST_ACCEPTED,
    REASON_LATENCY_GATE,
    REASON_QUALITY_GATE,
    STANDARD,
    FastTierConfig,
    FastTierRouter,
    ManualClock,
    StaticScorer,
    Task,
    build_clock_runner,
    route_all,
)


def _router(
    *,
    clock: ManualClock,
    fast_outputs: dict[str, str],
    fast_latencies: dict[str, float],
    scores: dict[str, float],
    config: FastTierConfig,
    std_outputs: dict[str, str] | None = None,
    std_latencies: dict[str, float] | None = None,
) -> FastTierRouter:
    fast_runner = build_clock_runner(clock, fast_outputs, fast_latencies)
    standard_runner = build_clock_runner(
        clock,
        std_outputs or {},
        std_latencies or {},
        default_output="standard-answer",
        default_latency=5.0,
    )
    return FastTierRouter(
        config=config,
        fast_runner=fast_runner,
        standard_runner=standard_runner,
        quality_scorer=StaticScorer(scores=scores, default=1.0),
        clock=clock.now,
    )


def test_within_budget_and_above_quality_routes_to_fast_and_records() -> None:
    clock = ManualClock()
    config = FastTierConfig(latency_budget_s=2.0, quality_gate=0.8)
    router = _router(
        clock=clock,
        fast_outputs={"t1": "fast-answer"},
        fast_latencies={"t1": 1.5},
        scores={"t1": 0.95},
        config=config,
    )

    result = router.route(Task(task_id="t1", expected_latency_s=1.0))

    assert result.tier_used == FAST
    assert result.reason == REASON_FAST_ACCEPTED
    assert result.fast_attempted is True
    assert result.fell_back is False
    # Latency is measured via the injected clock, not the expected estimate.
    assert result.latency_s == pytest.approx(1.5)
    assert result.quality == pytest.approx(0.95)
    assert result.latency_gate_passed is True
    assert result.quality_gate_passed is True
    assert result.output == "fast-answer"
    assert router.fallbacks == ()


def test_latency_gate_breach_is_not_fast_tiered() -> None:
    clock = ManualClock()
    config = FastTierConfig(latency_budget_s=2.0, quality_gate=0.5)
    router = _router(
        clock=clock,
        fast_outputs={"slow": "fast-answer"},
        fast_latencies={"slow": 0.1},
        scores={"slow": 1.0},  # would pass quality, but latency gate blocks it
        config=config,
        std_latencies={"slow": 4.0},
    )

    # expected_latency_s (3.0) exceeds the budget (2.0) -> never fast-tiered.
    result = router.route(Task(task_id="slow", expected_latency_s=3.0))

    assert result.tier_used == STANDARD
    assert result.reason == REASON_LATENCY_GATE
    assert result.fast_attempted is False
    assert result.fell_back is False
    assert result.latency_gate_passed is False
    # The standard tier still ran and its latency was recorded.
    assert result.latency_s == pytest.approx(4.0)
    assert result.output == "standard-answer"


def test_below_quality_gate_falls_back_to_standard_and_records() -> None:
    clock = ManualClock()
    config = FastTierConfig(latency_budget_s=2.0, quality_gate=0.8)
    router = _router(
        clock=clock,
        fast_outputs={"t2": "sloppy-fast"},
        fast_latencies={"t2": 1.0},
        scores={"t2": 0.4},  # below the 0.8 quality gate
        config=config,
        std_outputs={"t2": "solid-standard"},
        std_latencies={"t2": 6.0},
    )

    result = router.route(Task(task_id="t2", expected_latency_s=1.0))

    assert result.tier_used == STANDARD
    assert result.reason == REASON_QUALITY_GATE
    assert result.fast_attempted is True
    assert result.fell_back is True
    assert result.latency_gate_passed is True
    assert result.quality_gate_passed is False
    assert result.output == "solid-standard"
    # The fallback is recorded on the router history.
    assert len(router.fallbacks) == 1
    assert router.fallbacks[0].task_id == "t2"


def test_benchmark_produces_per_task_report_with_both_gates() -> None:
    clock = ManualClock()
    config = FastTierConfig(latency_budget_s=2.0, quality_gate=0.8, min_pass_ratio=1.0)
    router = _router(
        clock=clock,
        fast_outputs={"good": "g", "slow": "s", "poor": "p"},
        fast_latencies={"good": 1.0, "slow": 3.0, "poor": 1.0},
        scores={"good": 0.9, "slow": 0.9, "poor": 0.3},
        config=config,
    )

    report = router.benchmark(
        [
            Task(task_id="good", expected_latency_s=1.0),
            Task(task_id="slow", expected_latency_s=1.0),
            Task(task_id="poor", expected_latency_s=1.0),
        ]
    )

    good = report.result_for("good")
    slow = report.result_for("slow")
    poor = report.result_for("poor")
    assert good is not None and slow is not None and poor is not None

    # good clears both gates.
    assert good.latency_s == pytest.approx(1.0)
    assert good.quality == pytest.approx(0.9)
    assert good.latency_gate_passed is True
    assert good.quality_gate_passed is True
    assert good.passed is True

    # slow breaches the (measured) latency gate only.
    assert slow.latency_gate_passed is False
    assert slow.quality_gate_passed is True
    assert slow.passed is False

    # poor breaches the quality gate only.
    assert poor.latency_gate_passed is True
    assert poor.quality_gate_passed is False
    assert poor.passed is False

    # Overall eligibility: not every task passed both gates.
    assert report.pass_ratio == pytest.approx(1 / 3)
    assert report.eligible is False


def test_benchmark_eligible_when_all_pass_both_gates() -> None:
    clock = ManualClock()
    config = FastTierConfig(latency_budget_s=2.0, quality_gate=0.8, min_pass_ratio=1.0)
    router = _router(
        clock=clock,
        fast_outputs={"a": "a", "b": "b"},
        fast_latencies={"a": 1.0, "b": 1.9},
        scores={"a": 0.85, "b": 0.99},
        config=config,
    )

    report = router.benchmark([Task(task_id="a", expected_latency_s=1.0), Task(task_id="b", expected_latency_s=1.0)])

    assert all(r.passed for r in report.results)
    assert report.pass_ratio == pytest.approx(1.0)
    assert report.eligible is True


def test_determinism_via_injected_clock_and_scorer() -> None:
    config = FastTierConfig(latency_budget_s=2.0, quality_gate=0.8)
    tasks = [
        Task(task_id="t1", expected_latency_s=1.0),
        Task(task_id="t2", expected_latency_s=1.0),
    ]

    def build() -> FastTierRouter:
        clock = ManualClock()
        return _router(
            clock=clock,
            fast_outputs={"t1": "o1", "t2": "o2"},
            fast_latencies={"t1": 1.25, "t2": 0.75},
            scores={"t1": 0.9, "t2": 0.85},
            config=config,
        )

    first = [(r.task_id, r.tier_used, r.latency_s, r.quality) for r in route_all(build(), tasks)]
    second = [(r.task_id, r.tier_used, r.latency_s, r.quality) for r in route_all(build(), tasks)]

    assert first == second
    assert first == [
        ("t1", FAST, pytest.approx(1.25), pytest.approx(0.9)),
        ("t2", FAST, pytest.approx(0.75), pytest.approx(0.85)),
    ]


def test_config_rejects_invalid_thresholds() -> None:
    with pytest.raises(ValueError):
        FastTierConfig(latency_budget_s=0.0, quality_gate=0.5)
    with pytest.raises(ValueError):
        FastTierConfig(latency_budget_s=1.0, quality_gate=1.5)
    with pytest.raises(ValueError):
        FastTierConfig(latency_budget_s=1.0, quality_gate=0.5, min_pass_ratio=2.0)
