"""CAP-103 L2: dispatch a task to a registered mobile device and reconcile its
delivery/result state with bounded retry.

Proves (all hermetic -- injected clock + injected FakeChannel, no network):

- A task dispatched to a **registered** device is delivered over the fake
  channel and its state advances to ``delivered``.
- A **device-reported result** reconciles the task's state to ``completed``.
- A **no-ack past the deadline** triggers a bounded retry and, at the cap,
  moves the task to the ``failed`` terminal state.
- Dispatch to an **unknown device id** is *rejected* (raises), not silently
  dropped -- no task is created.
- **Determinism**: replaying the same operations with the same injected clock
  and channel yields an identical state history.

The real APNs/FCM push edge (:class:`PushServiceChannel`) is the documented
live lane and is intentionally NOT exercised here.
"""

from __future__ import annotations

import pytest

from thomas.tools.mobile_dispatch import (
    STATE_COMPLETED,
    STATE_DELIVERED,
    STATE_FAILED,
    FakeChannel,
    MobileDispatchService,
    TaskStateError,
    UnknownDeviceError,
)


class FakeClock:
    """Deterministic, manually-advanced clock."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


def _service(channel: FakeChannel, clock: FakeClock, **kwargs) -> MobileDispatchService:
    params = {"clock": clock, "ack_deadline_s": 30.0, "retry_cap": 2}
    params.update(kwargs)
    return MobileDispatchService(channel, **params)


def test_dispatch_to_registered_device_advances_to_delivered() -> None:
    clock = FakeClock()
    channel = FakeChannel()
    svc = _service(channel, clock)
    svc.register_device("phone-1", push_token="tok-abc", platform="ios")

    task = svc.dispatch("phone-1", {"kind": "sync", "n": 1})

    assert task.state == STATE_DELIVERED
    assert len(channel.sent) == 1
    token, task_id, payload = channel.sent[0]
    assert token == "tok-abc"
    assert task_id == task.task_id
    assert payload == {"kind": "sync", "n": 1}
    assert task.receipts[-1].delivered is True
    assert task.history[-1].to_state == STATE_DELIVERED


def test_device_reported_result_reconciles_to_completed() -> None:
    clock = FakeClock()
    svc = _service(FakeChannel(), clock)
    svc.register_device("phone-1", push_token="tok-abc")

    task = svc.dispatch("phone-1", {"job": "backup"})
    assert task.state == STATE_DELIVERED

    svc.reconcile_ack(task.task_id)
    assert svc.get_task(task.task_id).state == "acked"

    reconciled = svc.reconcile_result(task.task_id, success=True, result={"bytes": 42})
    assert reconciled.state == STATE_COMPLETED
    assert reconciled.is_terminal is True
    assert reconciled.result == {"bytes": 42}


def test_result_before_explicit_ack_still_completes() -> None:
    clock = FakeClock()
    svc = _service(FakeChannel(), clock)
    svc.register_device("phone-1", push_token="tok-abc")
    task = svc.dispatch("phone-1", {"job": "ping"})

    # Device reports a result without a prior explicit ack -> implicit ack.
    reconciled = svc.reconcile_result(task.task_id, success=True)
    assert reconciled.state == STATE_COMPLETED
    states = [t.to_state for t in reconciled.history]
    assert "acked" in states and states[-1] == STATE_COMPLETED


def test_device_reported_failure_reconciles_to_failed() -> None:
    clock = FakeClock()
    svc = _service(FakeChannel(), clock)
    svc.register_device("phone-1", push_token="tok-abc")
    task = svc.dispatch("phone-1", {"job": "x"})

    reconciled = svc.reconcile_result(task.task_id, success=False, result={"err": "boom"})
    assert reconciled.state == STATE_FAILED
    assert reconciled.is_terminal is True


def test_no_ack_past_deadline_retries_then_fails_at_cap() -> None:
    clock = FakeClock()
    channel = FakeChannel()
    svc = _service(channel, clock, ack_deadline_s=30.0, retry_cap=2)
    svc.register_device("phone-1", push_token="tok-abc")

    task = svc.dispatch("phone-1", {"job": "watch"})
    assert task.state == STATE_DELIVERED
    assert len(channel.sent) == 1  # initial dispatch send

    # Before the deadline: nothing happens.
    clock.advance(10)
    assert svc.reconcile_deadlines() == []
    assert svc.get_task(task.task_id).state == STATE_DELIVERED

    # First deadline miss -> bounded retry #1 (re-sent over the channel).
    clock.advance(25)  # now 35 > deadline 30
    acted = svc.reconcile_deadlines()
    assert [t.task_id for t in acted] == [task.task_id]
    task = svc.get_task(task.task_id)
    assert task.retry_count == 1
    assert task.state == STATE_DELIVERED
    assert len(channel.sent) == 2

    # Second deadline miss -> retry #2 (at the cap of re-sends).
    clock.advance(31)
    svc.reconcile_deadlines()
    task = svc.get_task(task.task_id)
    assert task.retry_count == 2
    assert len(channel.sent) == 3

    # Third deadline miss -> cap reached, terminal failure, no further send.
    clock.advance(31)
    acted = svc.reconcile_deadlines()
    task = svc.get_task(task.task_id)
    assert task.state == STATE_FAILED
    assert task.is_terminal is True
    assert task.retry_count == 2
    assert len(channel.sent) == 3  # no send on the failing pass
    assert "cap reached" in task.history[-1].reason

    # Terminal: further deadline passes are inert.
    clock.advance(100)
    assert svc.reconcile_deadlines() == []


def test_retry_then_ack_before_cap_recovers() -> None:
    clock = FakeClock()
    channel = FakeChannel()
    svc = _service(channel, clock, ack_deadline_s=30.0, retry_cap=2)
    svc.register_device("phone-1", push_token="tok-abc")
    task = svc.dispatch("phone-1", {"job": "y"})

    clock.advance(31)
    svc.reconcile_deadlines()  # retry #1
    assert svc.get_task(task.task_id).retry_count == 1

    # Device acks after the retry -> deadline cleared, no more retries/failure.
    svc.reconcile_ack(task.task_id)
    assert svc.get_task(task.task_id).state == "acked"

    clock.advance(500)
    assert svc.reconcile_deadlines() == []
    done = svc.reconcile_result(task.task_id, success=True)
    assert done.state == STATE_COMPLETED


def test_delivery_failure_is_retried_not_dropped() -> None:
    clock = FakeClock()
    # Channel fails the first two sends for this token, then succeeds.
    channel = FakeChannel(fail_first={"tok-abc": 2})
    svc = _service(channel, clock, ack_deadline_s=30.0, retry_cap=3)
    svc.register_device("phone-1", push_token="tok-abc")

    task = svc.dispatch("phone-1", {"job": "z"})
    # First send failed -> task stays pending (queued), not delivered, not dropped.
    assert task.state == "queued"
    assert task.receipts[-1].delivered is False

    clock.advance(31)
    svc.reconcile_deadlines()  # retry #1 -> second send also fails
    task = svc.get_task(task.task_id)
    assert task.state == "queued"
    assert task.retry_count == 1

    clock.advance(31)
    svc.reconcile_deadlines()  # retry #2 -> third send succeeds
    task = svc.get_task(task.task_id)
    assert task.state == STATE_DELIVERED
    assert task.retry_count == 2


def test_dispatch_to_unknown_device_is_rejected() -> None:
    clock = FakeClock()
    channel = FakeChannel()
    svc = _service(channel, clock)
    # Note: no device registered.

    with pytest.raises(UnknownDeviceError):
        svc.dispatch("ghost-device", {"job": "nope"})

    # Rejected, not silently dropped: no task created, nothing sent.
    assert svc.tasks() == []
    assert channel.sent == []


def test_invalid_state_transitions_raise() -> None:
    clock = FakeClock()
    svc = _service(FakeChannel(), clock)
    svc.register_device("phone-1", push_token="tok-abc")
    task = svc.dispatch("phone-1", {"job": "q"})

    svc.reconcile_ack(task.task_id)
    # Cannot ack twice.
    with pytest.raises(TaskStateError):
        svc.reconcile_ack(task.task_id)

    svc.reconcile_result(task.task_id, success=True)
    # Cannot reconcile a terminal task's result again.
    with pytest.raises(TaskStateError):
        svc.reconcile_result(task.task_id, success=True)


def _run_scenario() -> list[tuple[str, str, str, float]]:
    """Replayable scenario -> flattened (task_id, from, to, at) history."""
    clock = FakeClock()
    channel = FakeChannel(fail_tokens={"tok-bad"})
    svc = _service(channel, clock, ack_deadline_s=30.0, retry_cap=2)
    svc.register_device("good", push_token="tok-good")
    svc.register_device("bad", push_token="tok-bad")

    t_ok = svc.dispatch("good", {"n": 1})
    t_bad = svc.dispatch("bad", {"n": 2})
    svc.reconcile_ack(t_ok.task_id)
    svc.reconcile_result(t_ok.task_id, success=True)

    for _ in range(4):
        clock.advance(31)
        svc.reconcile_deadlines()

    flat: list[tuple[str, str, str, float]] = []
    for task in svc.tasks():
        for tr in task.history:
            flat.append((task.task_id, tr.from_state, tr.to_state, tr.at))
    return flat


def test_determinism_same_inputs_same_history() -> None:
    first = _run_scenario()
    second = _run_scenario()
    assert first == second
    # Sanity: the scenario actually drove both a completed and a failed task.
    to_states = {row[2] for row in first}
    assert STATE_COMPLETED in to_states
    assert STATE_FAILED in to_states
