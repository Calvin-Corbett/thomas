"""Tests for CAP-137 live run telemetry aggregation + projection.

Every test drives :class:`RunProjection` with an injected clock and events that
carry explicit timestamps, so the numbers are fully deterministic. There is no
wall-clock read and no network anywhere.
"""

from __future__ import annotations

import math

import pytest

from thomas.observability.run_projection import (
    EventKind,
    RunEvent,
    RunProjection,
    RunSnapshot,
    RunTarget,
)


class FakeClock:
    """A controllable monotonic clock; ``now`` is advanced explicitly."""

    def __init__(self, start: float = 0.0) -> None:
        self.value = start

    def __call__(self) -> float:
        return self.value

    def set(self, value: float) -> None:
        self.value = value


def test_live_turns_and_tokens_are_cumulative() -> None:
    clock = FakeClock()
    proj = RunProjection(window_seconds=60.0, clock=clock)

    proj.turn_started(0.0)
    proj.record_tokens(100, 1.0)
    proj.turn_finished(2.0)
    proj.turn_started(2.0)
    proj.record_tokens(150, 3.0)
    proj.turn_finished(4.0)

    clock.set(4.0)
    snap = proj.snapshot()

    assert snap.cumulative_turns == 2
    assert snap.cumulative_tokens == 250
    assert snap.turns_in_progress == 0


def test_turns_in_progress_tracks_open_turns() -> None:
    clock = FakeClock()
    proj = RunProjection(clock=clock)

    proj.turn_started(0.0)
    proj.turn_started(1.0)
    proj.turn_finished(2.0)

    clock.set(2.0)
    snap = proj.snapshot()

    assert snap.cumulative_turns == 1
    assert snap.turns_in_progress == 1


def test_rate_reflects_rolling_window() -> None:
    clock = FakeClock()
    proj = RunProjection(window_seconds=60.0, clock=clock)

    # 600 tokens spread across t = 0,30,60 (200 each).
    proj.record_tokens(200, 0.0)
    proj.record_tokens(200, 30.0)
    proj.record_tokens(200, 60.0)

    # At now=60 the window is (0, 60]; the t=0 event has aged out (half-open).
    # In-window tokens = 200 + 200 = 400, oldest in-window ts = 30, span = 30s.
    clock.set(60.0)
    snap = proj.snapshot()
    assert snap.tokens_per_min == pytest.approx(400.0 / 30.0 * 60.0)

    # Advance to now=90: window is (30, 90]. Only the t=60 event survives.
    # tokens = 200, oldest = 60, span = 30s.
    clock.set(90.0)
    snap2 = proj.snapshot()
    assert snap2.tokens_per_min == pytest.approx(200.0 / 30.0 * 60.0)

    # Advance past every event: window empties -> rate unknown, not zero-div.
    clock.set(200.0)
    snap3 = proj.snapshot()
    assert snap3.tokens_per_min is None
    assert snap3.turns_per_min is None


def test_turn_rate_is_measured_over_window() -> None:
    clock = FakeClock()
    proj = RunProjection(window_seconds=120.0, clock=clock)

    proj.turn_finished(0.0)
    proj.turn_finished(30.0)
    proj.turn_finished(60.0)

    # now=60, window (-60, 60]: 3 finished turns, oldest ts=0, span=60s.
    clock.set(60.0)
    snap = proj.snapshot()
    assert snap.turns_per_min == pytest.approx(3.0 / 60.0 * 60.0)  # 3 turns/min


def test_completion_projection_estimates_remaining_and_eta() -> None:
    clock = FakeClock()
    proj = RunProjection(
        window_seconds=60.0,
        clock=clock,
        target=RunTarget(turns=10, tokens=1000),
    )

    # Consume 300 tokens and 3 turns over 30 seconds -> 10 tokens/s, 0.1 turns/s.
    proj.turn_finished(0.0)
    proj.record_tokens(100, 0.0)
    proj.turn_finished(15.0)
    proj.record_tokens(100, 15.0)
    proj.turn_finished(30.0)
    proj.record_tokens(100, 30.0)

    clock.set(30.0)
    snap = proj.snapshot()

    assert snap.cumulative_turns == 3
    assert snap.cumulative_tokens == 300
    assert snap.remaining_turns == 7
    assert snap.remaining_tokens == 700

    # token rate: in-window tokens = 300, oldest ts=0, span=30 -> 10 tok/s.
    # eta_tokens = 700 / 10 = 70s.
    assert snap.eta_seconds_tokens == pytest.approx(70.0)
    # turn rate: 3 turns over span 30s -> 0.1 turns/s. eta_turns = 7/0.1 = 70s.
    assert snap.eta_seconds_turns == pytest.approx(70.0)
    # bottleneck = max(70, 70) = 70.
    assert snap.eta_seconds == pytest.approx(70.0)
    assert snap.projection_known is True


def test_projection_updates_as_rate_changes() -> None:
    clock = FakeClock()
    proj = RunProjection(
        window_seconds=60.0,
        clock=clock,
        target=RunTarget(tokens=1000),
    )

    # First burst: 100 tokens over 10s -> 10 tok/s. remaining 900 -> eta 90s.
    proj.record_tokens(50, 0.0)
    proj.record_tokens(50, 10.0)
    clock.set(10.0)
    first = proj.snapshot()
    assert first.remaining_tokens == 900
    assert first.eta_seconds_tokens == pytest.approx(900.0 / (100.0 / 10.0))

    # Rate doubles: add 300 tokens by t=20. Window (−40,20]: tokens=400 over
    # span 20s -> 20 tok/s. remaining 600 -> eta 30s (faster than before).
    proj.record_tokens(300, 20.0)
    clock.set(20.0)
    second = proj.snapshot()
    assert second.cumulative_tokens == 400
    assert second.remaining_tokens == 600
    assert second.eta_seconds_tokens == pytest.approx(600.0 / (400.0 / 20.0))
    assert second.eta_seconds_tokens < first.eta_seconds_tokens


def test_zero_rate_projection_is_unknown_not_divide_by_zero() -> None:
    clock = FakeClock()
    proj = RunProjection(
        window_seconds=30.0,
        clock=clock,
        target=RunTarget(tokens=1000),
    )

    proj.record_tokens(100, 0.0)

    # Advance well past the window so no token events remain in it.
    clock.set(500.0)
    snap = proj.snapshot()

    assert snap.tokens_per_min is None
    assert snap.remaining_tokens == 900  # still has work
    assert snap.eta_seconds_tokens is None  # unknown, not inf / not 0
    assert snap.eta_seconds is None
    assert snap.projection_known is False


def test_insufficient_data_projection_is_unknown() -> None:
    clock = FakeClock()
    proj = RunProjection(
        window_seconds=60.0,
        clock=clock,
        target=RunTarget(tokens=500),
    )

    # A single token event *at* now gives a zero span -> rate undefined.
    proj.record_tokens(100, 5.0)
    clock.set(5.0)
    snap = proj.snapshot()

    assert snap.tokens_per_min is None
    assert snap.eta_seconds_tokens is None
    assert snap.projection_known is False


def test_completed_target_reports_zero_eta() -> None:
    clock = FakeClock()
    proj = RunProjection(
        window_seconds=60.0,
        clock=clock,
        target=RunTarget(turns=2, tokens=100),
    )

    proj.turn_finished(0.0)
    proj.record_tokens(60, 0.0)
    proj.turn_finished(10.0)
    proj.record_tokens(60, 10.0)

    clock.set(10.0)
    snap = proj.snapshot()

    # Both targets met (2 turns, 120 >= 100 tokens).
    assert snap.remaining_turns == 0
    assert snap.remaining_tokens == 0
    assert snap.eta_seconds == pytest.approx(0.0)
    assert snap.projection_known is True


def test_bottleneck_is_the_slower_dimension() -> None:
    clock = FakeClock()
    proj = RunProjection(
        window_seconds=120.0,
        clock=clock,
        target=RunTarget(turns=100, tokens=200),
    )

    # Fast tokens, slow turns.
    proj.record_tokens(50, 0.0)
    proj.record_tokens(50, 10.0)  # 100 tokens over 10s -> 10 tok/s
    proj.turn_finished(0.0)
    proj.turn_finished(10.0)  # 2 turns over 10s -> 0.2 turns/s

    clock.set(10.0)
    snap = proj.snapshot()

    # tokens: remaining 100 / 10 = 10s. turns: remaining 98 / 0.2 = 490s.
    assert snap.eta_seconds_tokens == pytest.approx(10.0)
    assert snap.eta_seconds_turns == pytest.approx(490.0)
    assert snap.eta_seconds == pytest.approx(490.0)  # bottleneck = turns


def test_no_target_projection_known_with_no_eta() -> None:
    clock = FakeClock()
    proj = RunProjection(window_seconds=60.0, clock=clock)

    proj.record_tokens(100, 0.0)
    proj.record_tokens(100, 10.0)
    clock.set(10.0)
    snap = proj.snapshot()

    assert snap.target_tokens is None
    assert snap.remaining_tokens is None
    assert snap.eta_seconds is None
    assert snap.projection_known is True  # nothing to reach == not "unknown"


def test_always_visible_snapshot_before_any_events() -> None:
    clock = FakeClock()
    proj = RunProjection(clock=clock, target=RunTarget(tokens=100))

    snap = proj.snapshot()

    assert isinstance(snap, RunSnapshot)
    assert snap.cumulative_turns == 0
    assert snap.cumulative_tokens == 0
    assert snap.tokens_per_min is None
    assert snap.remaining_tokens == 100
    assert snap.eta_seconds is None
    assert snap.projection_known is False


def test_snapshot_is_deterministic() -> None:
    def build() -> RunSnapshot:
        clock = FakeClock()
        proj = RunProjection(
            window_seconds=45.0,
            clock=clock,
            target=RunTarget(turns=8, tokens=800),
        )
        proj.ingest_many(
            [
                RunEvent(EventKind.TURN_STARTED, 0.0),
                RunEvent(EventKind.TOKENS, 5.0, tokens=120),
                RunEvent(EventKind.TURN_FINISHED, 10.0),
                RunEvent(EventKind.TOKENS, 15.0, tokens=130),
                RunEvent(EventKind.TURN_FINISHED, 20.0),
            ]
        )
        clock.set(20.0)
        return proj.snapshot()

    first = build()
    second = build()
    assert first == second
    assert first.as_dict() == second.as_dict()
    # ETA is a real finite number here, so determinism is non-trivial.
    assert first.eta_seconds is not None
    assert math.isfinite(first.eta_seconds)


def test_window_seconds_must_be_positive() -> None:
    with pytest.raises(ValueError):
        RunProjection(window_seconds=0.0)
