"""Tests for the CAP-048 constraint envelope.

Proves the exact acceptance line: token ceilings, checkpoint summaries, and
deterministic stop reasons.
"""

from __future__ import annotations

from pathlib import Path

from thomas.agent.constraint_envelope import (
    CheckpointSummary,
    ConstraintEnvelope,
    EnvelopeDecision,
    StopReason,
    envelope_events,
)
from thomas.core.events import EventType

ROOT = Path(__file__).resolve().parent.parent


def test_token_ceiling_yields_exactly_token_ceiling_reached() -> None:
    env = ConstraintEnvelope(token_ceiling=1000)

    below = env.observe(999)
    assert below.stop_reason is StopReason.CONTINUE
    assert below.should_stop is False

    at = env.observe(1000)
    assert at.stop_reason is StopReason.TOKEN_CEILING_REACHED
    assert at.should_stop is True
    assert at.token_ceiling == 1000
    assert at.tokens_used == 1000
    assert "1000" in at.stop_message


def test_token_ceiling_reached_when_overshooting() -> None:
    env = ConstraintEnvelope(token_ceiling=500)
    decision = env.observe(5000)
    assert decision.stop_reason is StopReason.TOKEN_CEILING_REACHED
    assert decision.tokens_used == 5000


def test_checkpoints_fire_at_configured_interval_with_summary_payload() -> None:
    env = ConstraintEnvelope(checkpoint_every_tokens=1000)

    assert env.observe(500).checkpoint_summary is None

    first = env.observe(1000)
    assert first.stop_reason is StopReason.CHECKPOINT_DUE
    assert first.should_stop is False
    summary = first.checkpoint_summary
    assert isinstance(summary, CheckpointSummary)
    assert summary.checkpoint_index == 1
    payload = summary.to_dict()
    assert payload["checkpoint_index"] == 1
    assert payload["tokens_used"] == 1000
    assert payload["checkpoint_every_tokens"] == 1000
    assert payload["summary_requested"] is True

    # No new checkpoint until the next interval boundary is crossed.
    assert env.observe(1500).checkpoint_summary is None

    second = env.observe(2000)
    assert second.checkpoint_summary is not None
    assert second.checkpoint_summary.checkpoint_index == 2


def test_checkpoint_jump_advances_to_latest_milestone_once() -> None:
    env = ConstraintEnvelope(checkpoint_every_tokens=1000)
    decision = env.observe(3300)
    assert decision.checkpoint_summary is not None
    assert decision.checkpoint_summary.checkpoint_index == 3
    assert env.checkpoints_emitted == 3
    # Already past the third milestone: no duplicate fire.
    assert env.observe(3400).checkpoint_summary is None


def test_same_sequence_yields_same_decisions_deterministically() -> None:
    sequence = [0, 250, 500, 1000, 1000, 1500, 2000, 4000]

    def run() -> list[tuple[str, int | None, int]]:
        env = ConstraintEnvelope(token_ceiling=4000, checkpoint_every_tokens=1000)
        out: list[tuple[str, int | None, int]] = []
        for value in sequence:
            decision = env.observe(value)
            index = None if decision.checkpoint_summary is None else decision.checkpoint_summary.checkpoint_index
            out.append((decision.stop_reason.value, index, decision.tokens_used))
        return out

    assert run() == run()


def test_monotonic_clamp_prevents_backward_token_reports() -> None:
    env = ConstraintEnvelope(token_ceiling=1000, checkpoint_every_tokens=500)
    env.observe(600)
    # A provider under-report must not rewind cumulative spend or checkpoints.
    decision = env.observe(100)
    assert decision.tokens_used == 600
    assert env.checkpoints_emitted == 1


def test_no_ceiling_envelope_never_stops() -> None:
    env = ConstraintEnvelope(token_ceiling=None, checkpoint_every_tokens=None)
    for value in (10, 10_000, 10_000_000):
        decision = env.observe(value)
        assert decision.stop_reason is StopReason.CONTINUE
        assert decision.should_stop is False
        assert decision.checkpoint_summary is None
    assert env.active is False


def test_state_round_trip_preserves_behavior() -> None:
    env = ConstraintEnvelope(token_ceiling=3000, checkpoint_every_tokens=1000)
    env.observe(1000)
    env.observe(2200)

    restored = ConstraintEnvelope.from_state(env.to_state())
    assert restored.token_ceiling == 3000
    assert restored.checkpoint_every_tokens == 1000
    assert restored.tokens_used == 2200
    assert restored.checkpoints_emitted == 2

    # Resumed envelope continues deterministically from where it left off:
    # no duplicate checkpoint for an already-emitted milestone.
    assert restored.observe(2200).checkpoint_summary is None
    next_checkpoint = restored.observe(3000)
    assert next_checkpoint.checkpoint_summary is not None
    assert next_checkpoint.checkpoint_summary.checkpoint_index == 3
    assert next_checkpoint.stop_reason is StopReason.TOKEN_CEILING_REACHED


def test_from_state_rejects_unknown_version() -> None:
    try:
        ConstraintEnvelope.from_state({"version": 99})
    except ValueError as exc:
        assert "version" in str(exc).lower()
    else:  # pragma: no cover - explicit failure path
        raise AssertionError("expected ValueError for unknown state version")


def test_from_env_is_inert_without_configuration() -> None:
    env = ConstraintEnvelope.from_env({})
    assert env.token_ceiling is None
    assert env.checkpoint_every_tokens is None
    assert env.active is False


def test_from_env_reads_ceiling_and_checkpoint() -> None:
    env = ConstraintEnvelope.from_env({"THOMAS_TOKEN_CEILING": "5000", "THOMAS_TOKEN_CHECKPOINT_EVERY": "1000"})
    assert env.token_ceiling == 5000
    assert env.checkpoint_every_tokens == 1000
    assert env.active is True
    # Non-positive / garbage values are ignored, keeping the envelope inert.
    bad = ConstraintEnvelope.from_env({"THOMAS_TOKEN_CEILING": "0", "THOMAS_TOKEN_CHECKPOINT_EVERY": "abc"})
    assert bad.active is False


def test_complete_returns_terminal_completed_reason() -> None:
    env = ConstraintEnvelope(token_ceiling=1000)
    env.observe(200)
    decision = env.complete()
    assert decision.stop_reason is StopReason.COMPLETED
    assert decision.should_stop is True


def test_envelope_events_emits_status_and_ceiling_events() -> None:
    checkpoint_decision = EnvelopeDecision(
        stop_reason=StopReason.CHECKPOINT_DUE,
        tokens_used=1000,
        token_ceiling=4000,
        checkpoint_summary=CheckpointSummary(
            checkpoint_index=1,
            tokens_used=1000,
            token_ceiling=4000,
            checkpoint_every_tokens=1000,
            fraction_used=0.25,
            message="Checkpoint 1",
        ),
    )
    events = envelope_events(checkpoint_decision, iteration=2)
    assert len(events) == 1
    assert events[0].type == EventType.STATUS
    assert events[0].data["constraint_checkpoint"]["checkpoint_index"] == 1

    ceiling_decision = EnvelopeDecision(
        stop_reason=StopReason.TOKEN_CEILING_REACHED,
        tokens_used=4000,
        token_ceiling=4000,
        stop_message="Token ceiling reached",
    )
    ceiling_events = envelope_events(ceiling_decision, iteration=3)
    assert len(ceiling_events) == 1
    assert ceiling_events[0].type == EventType.AGENT_ERROR
    assert ceiling_events[0].data["stop_reason"] == "token_ceiling_reached"
    assert ceiling_events[0].data["token_ceiling"] == 4000


def test_continue_decision_emits_no_events() -> None:
    decision = EnvelopeDecision(
        stop_reason=StopReason.CONTINUE,
        tokens_used=10,
        token_ceiling=None,
    )
    assert envelope_events(decision, iteration=0) == []


def test_loop_execution_wires_the_constraint_envelope() -> None:
    # Source-contract check (mirrors test_agent_loop_monolith_contract style):
    # the envelope is constructed once and observed at the token-tracking point.
    source = (ROOT / "thomas" / "agent" / "loop_execution.py").read_text(encoding="utf-8")
    assert "from thomas.agent.constraint_envelope import ConstraintEnvelope, envelope_events" in source
    assert "constraint_envelope = ConstraintEnvelope.from_env()" in source
    assert 'constraint_envelope.observe(int(stream_usage.get("total_tokens", 0) or 0))' in source
    assert "if envelope_decision.should_stop:" in source
