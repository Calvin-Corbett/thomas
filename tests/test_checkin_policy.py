"""CAP-051 acceptance tests: configurable mid-run check-in policies with a
resumable user acknowledgement gate.

Acceptance line: "Add time/step/token check-in policies with a resumable user
acknowledgement gate."
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from thomas.agent.checkin_policy import (
    AcknowledgementGate,
    CheckinConfig,
    CheckinPolicy,
    checkin_config_from,
    resolve_checkin_policy,
)

ROOT = Path(__file__).resolve().parent.parent


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


# ── threshold triggers ──────────────────────────────────────────────────


def test_step_interval_triggers_every_n_tool_steps() -> None:
    policy = CheckinPolicy(CheckinConfig(step_interval=3), clock=FakeClock())

    assert policy.record_step(label="fs.read_file") is None
    assert policy.record_step(label="fs.read_file") is None
    event = policy.record_step(label="shell.run")

    assert event is not None
    assert event.thresholds_crossed == ("steps",)
    assert event.steps_since_last == 3
    assert event.total_steps == 3
    assert event.activity_since_last == ("fs.read_file", "fs.read_file", "shell.run")

    # Window resets: the next check-in needs three more steps.
    assert policy.record_step() is None
    assert policy.record_step() is None
    second = policy.record_step()
    assert second is not None
    assert second.sequence == 2
    assert second.total_steps == 6


def test_token_budget_triggers_every_n_tokens_consumed() -> None:
    policy = CheckinPolicy(CheckinConfig(token_interval=100), clock=FakeClock())

    assert policy.record_tokens(60) is None
    event = policy.record_tokens(50)

    assert event is not None
    assert event.thresholds_crossed == ("tokens",)
    assert event.tokens_since_last == 110
    assert event.total_tokens == 110

    # Absolute totals derive deltas (the loop reports cumulative usage).
    assert policy.record_tokens(150, absolute=True) is None  # +40 since 110
    absolute_event = policy.record_tokens(250, absolute=True)  # +100 more
    assert absolute_event is not None
    assert absolute_event.tokens_since_last == 140
    assert absolute_event.total_tokens == 250


def test_time_interval_triggers_after_elapsed_seconds() -> None:
    clock = FakeClock()
    policy = CheckinPolicy(CheckinConfig(interval_seconds=60), clock=clock)

    clock.advance(30)
    assert policy.record_step() is None

    clock.advance(31)
    event = policy.record_step()
    assert event is not None
    assert event.thresholds_crossed == ("time",)
    assert event.seconds_since_last >= 60

    # Timer window resets from the fire point.
    clock.advance(30)
    assert policy.record_step() is None
    clock.advance(31)
    assert policy.record_step() is not None


def test_combined_policy_each_threshold_triggers_independently() -> None:
    clock = FakeClock()
    policy = CheckinPolicy(
        CheckinConfig(interval_seconds=300, step_interval=5, token_interval=1000),
        clock=clock,
    )

    # Tokens cross first — only the token threshold is reported.
    token_event = policy.record_tokens(1000)
    assert token_event is not None
    assert token_event.thresholds_crossed == ("tokens",)

    # Steps cross next without tokens or time.
    for _ in range(4):
        assert policy.record_step() is None
    step_event = policy.record_step()
    assert step_event is not None
    assert step_event.thresholds_crossed == ("steps",)

    # Time crosses on its own at an otherwise quiet boundary.
    clock.advance(301)
    time_event = policy.check_time()
    assert time_event is not None
    assert time_event.thresholds_crossed == ("time",)


def test_multiple_thresholds_crossed_at_once_are_all_reported() -> None:
    clock = FakeClock()
    policy = CheckinPolicy(
        CheckinConfig(interval_seconds=60, step_interval=2, token_interval=100),
        clock=clock,
    )

    policy.record_tokens(99)
    assert policy.record_step() is None
    clock.advance(61)
    # observe_step records tokens (cumulative 100 -> +1 delta crosses the token
    # budget) at the same boundary where the time interval has elapsed.
    events = policy.observe_step(total_tokens=100)
    assert events, "expected at least one check-in"
    first = events[0]
    assert "tokens" in first.thresholds_crossed
    assert "time" in first.thresholds_crossed


# ── safe defaults: nothing configured, nothing fires ────────────────────


def test_no_policy_configured_resolves_to_none() -> None:
    assert resolve_checkin_policy(SimpleNamespace()) is None
    assert resolve_checkin_policy(None) is None
    assert resolve_checkin_policy({}) is None
    assert resolve_checkin_policy(SimpleNamespace(checkin=None)) is None
    # A checkin section with no thresholds set is still "not configured".
    assert resolve_checkin_policy({"checkin": {"ack_required": True}}) is None
    assert checkin_config_from(SimpleNamespace(checkin=SimpleNamespace())) is None


def test_disabled_policy_never_triggers() -> None:
    clock = FakeClock()
    policy = CheckinPolicy(CheckinConfig(), clock=clock)

    for _ in range(500):
        assert policy.record_step() is None
        assert policy.record_tokens(10_000) is None
        clock.advance(3600)
    assert policy.check_time() is None
    assert policy.observe_step(total_tokens=10**9) == []
    assert not policy.is_waiting()


def test_resolve_from_config_mapping_and_object() -> None:
    mapping_policy = resolve_checkin_policy({"checkin": {"step_interval": 2, "ack_required": True}})
    assert mapping_policy is not None
    assert mapping_policy.config.step_interval == 2
    assert mapping_policy.config.ack_required is True

    object_policy = resolve_checkin_policy(
        SimpleNamespace(checkin=SimpleNamespace(interval_seconds=90, token_interval=5000))
    )
    assert object_policy is not None
    assert object_policy.config.interval_seconds == 90.0
    assert object_policy.config.token_interval == 5000
    assert object_policy.config.ack_required is False

    # Invalid / non-positive values are treated as unset.
    assert resolve_checkin_policy({"checkin": {"step_interval": 0, "token_interval": "nope"}}) is None


# ── acknowledgement gate: pause and resume ──────────────────────────────


def test_ack_gate_pauses_run_until_acknowledged() -> None:
    async def scenario() -> None:
        policy = CheckinPolicy(CheckinConfig(step_interval=1, ack_required=True), clock=FakeClock())
        event = policy.record_step()
        assert event is not None
        assert event.ack_required is True
        assert policy.is_waiting()
        assert policy.gate.waiting_for == event.checkin_id

        waiter = asyncio.ensure_future(policy.wait_until_acknowledged())
        await asyncio.sleep(0.01)
        assert not waiter.done(), "run resumed before acknowledgement"

        # Wrong id does not release the gate.
        assert policy.acknowledge("not-the-id") is False
        await asyncio.sleep(0.01)
        assert not waiter.done()

        assert policy.acknowledge(event.checkin_id) is True
        await asyncio.wait_for(waiter, timeout=1.0)
        assert not policy.is_waiting()

        # Resumes exactly once: a second acknowledge is a no-op...
        assert policy.acknowledge() is False
        # ...and the gate stays open for subsequent waits until the next fire.
        await asyncio.wait_for(policy.wait_until_acknowledged(), timeout=1.0)

    asyncio.run(scenario())


def test_ack_not_required_leaves_gate_open() -> None:
    async def scenario() -> None:
        policy = CheckinPolicy(CheckinConfig(step_interval=1), clock=FakeClock())
        event = policy.record_step()
        assert event is not None
        assert event.ack_required is False
        assert not policy.is_waiting()
        await asyncio.wait_for(policy.wait_until_acknowledged(), timeout=1.0)

    asyncio.run(scenario())


def test_no_second_checkin_stacks_while_paused() -> None:
    policy = CheckinPolicy(CheckinConfig(step_interval=1, ack_required=True), clock=FakeClock())
    first = policy.record_step()
    assert first is not None
    # Further recording while paused never fires a second check-in.
    assert policy.record_step() is None
    assert policy.record_tokens(10**6) is None
    assert policy.gate.waiting_for == first.checkin_id


def test_gate_pauses_event_stream_until_acknowledged() -> None:
    """Mirror the loop wiring: an event stream that awaits the gate mid-run."""

    async def scenario() -> None:
        policy = CheckinPolicy(CheckinConfig(step_interval=2, ack_required=True), clock=FakeClock())
        seen: list[str] = []

        async def run_steps() -> None:
            for label in ("a", "b", "c", "d"):
                for checkin in policy.observe_step(total_tokens=0, label=label):
                    if checkin.ack_required:
                        await policy.wait_until_acknowledged()
                seen.append(label)

        runner = asyncio.ensure_future(run_steps())
        await asyncio.sleep(0.01)
        # Paused at the check-in after step "b": step "b" is not yet appended.
        assert seen == ["a"]
        assert policy.is_waiting()

        policy.acknowledge()
        await asyncio.sleep(0.01)
        # Resumed, then paused again at the check-in after step "d".
        assert seen == ["a", "b", "c"]
        assert policy.is_waiting()

        policy.acknowledge()
        await asyncio.wait_for(runner, timeout=1.0)
        assert seen == ["a", "b", "c", "d"]

    asyncio.run(scenario())


# ── persistence: paused run survives restart ────────────────────────────


def test_state_round_trip_preserves_pause_and_resumes_once_acknowledged() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        policy = CheckinPolicy(CheckinConfig(step_interval=3, ack_required=True), clock=clock)
        for _ in range(3):
            policy.record_step(label="shell.run")
        assert policy.is_waiting()
        pending_id = policy.gate.waiting_for
        assert pending_id

        # Two more steps into the next window, then "the process dies".
        # (Recording while paused is a no-op fire-wise but counters advance.)
        policy.record_step()
        policy.record_tokens(40)
        state = policy.to_state()

        # "New process": restore from the persisted dict.
        restored_clock = FakeClock(start=50_000.0)
        restored = CheckinPolicy.from_state(state, clock=restored_clock)

        assert restored.config.step_interval == 3
        assert restored.config.ack_required is True
        assert restored.is_waiting(), "pause must survive restart"
        assert restored.gate.waiting_for == pending_id
        assert restored.total_steps == 4
        assert restored.total_tokens == 40

        waiter = asyncio.ensure_future(restored.wait_until_acknowledged())
        await asyncio.sleep(0.01)
        assert not waiter.done(), "restored run resumed without acknowledgement"

        assert restored.acknowledge(pending_id) is True
        await asyncio.wait_for(waiter, timeout=1.0)
        assert not restored.is_waiting()

        # Counters carried over: one step already in the window, so two more
        # steps reach the step_interval=3 threshold again.
        assert restored.record_step() is None
        follow_up = restored.record_step()
        assert follow_up is not None
        assert follow_up.steps_since_last == 3
        assert follow_up.total_steps == 6

    asyncio.run(scenario())


def test_state_round_trip_preserves_elapsed_time_window() -> None:
    clock = FakeClock()
    policy = CheckinPolicy(CheckinConfig(interval_seconds=60), clock=clock)
    clock.advance(45)
    state = policy.to_state()

    restored_clock = FakeClock(start=9_999.0)
    restored = CheckinPolicy.from_state(state, clock=restored_clock)

    # 45s already elapsed pre-restart; 15 more seconds cross the threshold.
    restored_clock.advance(10)
    assert restored.check_time() is None
    restored_clock.advance(6)
    event = restored.check_time()
    assert event is not None
    assert event.thresholds_crossed == ("time",)


def test_gate_state_round_trip_standalone() -> None:
    gate = AcknowledgementGate()
    assert not gate.is_waiting()
    assert AcknowledgementGate.from_state(gate.to_state()).is_waiting() is False

    gate.require_ack("abc123")
    restored = AcknowledgementGate.from_state(gate.to_state())
    assert restored.is_waiting()
    assert restored.waiting_for == "abc123"
    assert restored.acknowledge("abc123") is True
    assert restored.is_waiting() is False


# ── event payload ───────────────────────────────────────────────────────


def test_checkin_event_payload_reports_progress_and_totals() -> None:
    clock = FakeClock()
    policy = CheckinPolicy(CheckinConfig(step_interval=2, ack_required=True), clock=clock)
    policy.record_tokens(120)
    policy.record_step(label="fs.write_file")
    clock.advance(12)
    event = policy.record_step(label="shell.run")

    assert event is not None
    payload = event.to_dict()
    assert payload["thresholds_crossed"] == ["steps"]
    assert payload["steps_since_last"] == 2
    assert payload["tokens_since_last"] == 120
    assert payload["seconds_since_last"] == 12
    assert payload["activity_since_last"] == ["fs.write_file", "shell.run"]
    assert payload["total_steps"] == 2
    assert payload["total_tokens"] == 120
    assert payload["ack_required"] is True
    assert payload["checkin_id"]
    assert "Paused" in event.message
    assert "2 tool step(s)" in event.message


# ── loop wiring contract ────────────────────────────────────────────────


def test_agent_loop_wires_checkin_policy_at_tool_step_boundary() -> None:
    """The agent loop instantiates the policy from config, observes each tool
    step, emits the check-in through the loop's event path, and awaits the
    acknowledgement gate (same source-contract style as the monolith tests).
    """
    source = (ROOT / "thomas/agent/loop_execution.py").read_text(encoding="utf-8")

    assert "from thomas.agent.checkin_policy import resolve_checkin_policy" in source
    assert "resolve_checkin_policy(self.config)" in source
    assert "checkin_policy.observe_step(" in source
    assert 'data={"message": checkin.message, "checkin": checkin.to_dict()}' in source
    assert "await checkin_policy.wait_until_acknowledged()" in source
    # Zero-overhead guard: every touchpoint is behind a None check.
    assert "if checkin_policy is not None:" in source
