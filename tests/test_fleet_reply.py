"""CAP-040 acceptance: inline reply/steer dispatch from the fleet dashboard.

Proves the backend core behind the dashboard's inline reply control:
  * a reply dispatched to a live session is DELIVERED and its receipt
    reconciles to ACKED once the session acknowledges it;
  * a reply to an UNKNOWN/ended session is REJECTED (not silently dropped);
  * an un-acked reply past the ack deadline surfaces as undelivered/FAILED;
  * receipts are ordered by dispatch;
  * the whole thing is deterministic under an injected clock + FakeChannel.

Hermetic: no network, injected clock, in-memory fake channel.
"""

import pytest

from thomas.agent.fleet_reply import (
    DEFAULT_ACK_DEADLINE_SECONDS,
    DeliveryChannel,
    DeliveryReceipt,
    DeliveryState,
    FleetReplyConfig,
    FleetReplyService,
    InboxChannel,
    ReceiptStateError,
    ReplyEnvelope,
    UnknownReceiptError,
    UnknownSessionError,
)


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def __call__(self) -> float:
        return self.now


class FakeChannel:
    """Hermetic delivery channel: records envelopes, scriptable outcome."""

    def __init__(self, *, accept: bool = True, raises: BaseException | None = None) -> None:
        self.accept = accept
        self.raises = raises
        self.delivered: list[ReplyEnvelope] = []

    def deliver(self, envelope: ReplyEnvelope) -> bool:
        if self.raises is not None:
            raise self.raises
        self.delivered.append(envelope)
        return self.accept


def _service(clock: FakeClock | None = None, deadline: float = 30.0) -> FleetReplyService:
    return FleetReplyService(config=FleetReplyConfig(ack_deadline_seconds=deadline), clock=clock or FakeClock())


# ---------------------------------------------------------------------------
# Happy path: delivered + reconciles to acked
# ---------------------------------------------------------------------------


def test_reply_to_live_session_is_delivered_then_acked():
    clock = FakeClock()
    svc = _service(clock)
    channel = FakeChannel()
    svc.register_session("sess-1", channel)

    clock.advance(2.0)
    receipt = svc.dispatch_reply("sess-1", "please focus on the failing test")

    assert receipt.state is DeliveryState.DELIVERED
    assert receipt.delivered_at == 2.0
    assert channel.delivered and channel.delivered[0].text == "please focus on the failing test"
    assert channel.delivered[0].session_id == "sess-1"

    # The target session acks receipt -> reconciles to acked.
    clock.advance(1.5)
    acked = svc.acknowledge(receipt.id)
    assert acked.state is DeliveryState.ACKED
    assert acked.is_acked
    assert acked.acked_at == 3.5
    # Server-side view agrees.
    assert svc.get_receipt(receipt.id).state is DeliveryState.ACKED


def test_acknowledge_is_idempotent():
    svc = _service()
    svc.register_session("s", FakeChannel())
    r = svc.dispatch_reply("s", "steer")
    first = svc.acknowledge(r.id)
    second = svc.acknowledge(r.id)
    assert first.state is second.state is DeliveryState.ACKED
    assert second.acked_at == first.acked_at  # not re-stamped


# ---------------------------------------------------------------------------
# Unknown / ended session is rejected, not dropped
# ---------------------------------------------------------------------------


def test_reply_to_unknown_session_is_rejected():
    svc = _service()
    with pytest.raises(UnknownSessionError) as exc:
        svc.dispatch_reply("ghost", "hello?")
    assert exc.value.session_id == "ghost"
    # Nothing was recorded -- rejected, not a silent half-receipt.
    assert svc.receipts() == ()


def test_reply_to_ended_session_is_rejected():
    svc = _service()
    svc.register_session("sess-1", FakeChannel())
    assert svc.is_registered("sess-1")
    # Session ends.
    assert svc.unregister_session("sess-1") is True
    assert not svc.is_registered("sess-1")
    with pytest.raises(UnknownSessionError):
        svc.dispatch_reply("sess-1", "too late")
    assert svc.unregister_session("sess-1") is False  # already gone


def test_empty_reply_text_is_rejected():
    svc = _service()
    svc.register_session("s", FakeChannel())
    for bad in ("", "   ", "\n\t"):
        with pytest.raises(ValueError):
            svc.dispatch_reply("s", bad)
    assert svc.receipts() == ()


# ---------------------------------------------------------------------------
# No-ack past the deadline -> undelivered / failed (bounded)
# ---------------------------------------------------------------------------


def test_unacked_reply_past_deadline_is_reported_undelivered():
    clock = FakeClock()
    svc = _service(clock, deadline=30.0)
    svc.register_session("s", FakeChannel())

    receipt = svc.dispatch_reply("s", "are you stuck?")
    assert receipt.state is DeliveryState.DELIVERED

    # Just before the deadline: still pending, nothing failed.
    clock.advance(29.0)
    assert svc.reconcile() == []
    assert svc.get_receipt(receipt.id).state is DeliveryState.DELIVERED

    # Past the deadline: reconciles to FAILED and is reported undelivered.
    clock.advance(2.0)  # total 31s >= 30s deadline
    failed = svc.reconcile()
    assert [r.id for r in failed] == [receipt.id]
    surfaced = svc.get_receipt(receipt.id)
    assert surfaced.state is DeliveryState.FAILED
    assert surfaced.is_failed
    assert surfaced.undelivered is True
    assert surfaced.reason == "ack_timeout"
    assert surfaced.failed_at == 31.0


def test_deadline_is_bounded_from_dispatch_not_from_delivery():
    clock = FakeClock()
    svc = _service(clock, deadline=10.0)
    svc.register_session("s", FakeChannel())
    r = svc.dispatch_reply("s", "steer")
    # Reconcile with an explicit 'now' exactly at the bound.
    assert [x.id for x in svc.reconcile(now=r.queued_at + DEFAULT_ACK_DEADLINE_SECONDS)] == [r.id]


def test_late_ack_after_timeout_does_not_resurrect_delivery():
    clock = FakeClock()
    svc = _service(clock, deadline=5.0)
    svc.register_session("s", FakeChannel())
    r = svc.dispatch_reply("s", "steer")
    clock.advance(6.0)
    svc.reconcile()
    assert svc.get_receipt(r.id).state is DeliveryState.FAILED
    with pytest.raises(ReceiptStateError):
        svc.acknowledge(r.id)
    assert svc.get_receipt(r.id).state is DeliveryState.FAILED  # still failed


def test_acked_reply_is_untouched_by_reconcile():
    clock = FakeClock()
    svc = _service(clock, deadline=5.0)
    svc.register_session("s", FakeChannel())
    r = svc.dispatch_reply("s", "steer")
    svc.acknowledge(r.id)
    clock.advance(1000.0)
    assert svc.reconcile() == []
    assert svc.get_receipt(r.id).state is DeliveryState.ACKED


# ---------------------------------------------------------------------------
# Channel failure surfaces (refusal + fault), never a silent drop
# ---------------------------------------------------------------------------


def test_channel_refusal_marks_receipt_failed():
    svc = _service()
    svc.register_session("s", FakeChannel(accept=False))
    r = svc.dispatch_reply("s", "steer")
    assert r.state is DeliveryState.FAILED
    assert r.reason == "channel_rejected"
    assert r.undelivered is True


def test_closed_inbox_channel_refuses_cleanly():
    svc = _service()
    inbox = InboxChannel(open=False)
    svc.register_session("s", inbox)
    r = svc.dispatch_reply("s", "steer")
    assert r.state is DeliveryState.FAILED
    assert r.undelivered is True


def test_channel_fault_is_caught_and_reported():
    svc = _service()
    svc.register_session("s", FakeChannel(raises=ConnectionError("socket gone")))
    r = svc.dispatch_reply("s", "steer")
    assert r.state is DeliveryState.FAILED
    assert r.reason is not None and "channel_error" in r.reason
    assert r.undelivered is True


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


def test_receipts_are_ordered_by_dispatch():
    clock = FakeClock()
    svc = _service(clock)
    svc.register_session("a", FakeChannel())
    svc.register_session("b", FakeChannel())
    ids = []
    for i in range(5):
        target = "a" if i % 2 == 0 else "b"
        clock.advance(1.0)
        ids.append(svc.dispatch_reply(target, f"steer-{i}").id)

    ordered = svc.receipts()
    assert [r.id for r in ordered] == ids
    assert [r.seq for r in ordered] == [1, 2, 3, 4, 5]
    # Per-session view preserves global dispatch order.
    assert [r.text for r in svc.receipts("a")] == ["steer-0", "steer-2", "steer-4"]


def test_unknown_receipt_lookup_and_ack_raise():
    svc = _service()
    with pytest.raises(UnknownReceiptError):
        svc.get_receipt("rcpt-999")
    with pytest.raises(UnknownReceiptError):
        svc.acknowledge("rcpt-999")


def test_pending_receipts_excludes_terminal():
    svc = _service()
    svc.register_session("s", FakeChannel())
    r1 = svc.dispatch_reply("s", "one")
    r2 = svc.dispatch_reply("s", "two")
    svc.acknowledge(r1.id)
    pending = svc.pending_receipts()
    assert [r.id for r in pending] == [r2.id]


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def _scripted_run() -> tuple[DeliveryReceipt, ...]:
    clock = FakeClock()
    svc = _service(clock, deadline=10.0)
    svc.register_session("s1", FakeChannel())
    svc.register_session("s2", FakeChannel(accept=False))
    clock.advance(1.0)
    r1 = svc.dispatch_reply("s1", "alpha")
    clock.advance(1.0)
    svc.dispatch_reply("s2", "beta")  # refused
    clock.advance(1.0)
    svc.dispatch_reply("s1", "gamma")  # will time out
    svc.acknowledge(r1.id)
    clock.advance(20.0)
    svc.reconcile()
    return svc.receipts()


def test_dispatch_sequence_is_deterministic():
    run_a = _scripted_run()
    run_b = _scripted_run()
    fields = [
        (r.id, r.session_id, r.text, r.seq, r.state, r.queued_at, r.delivered_at, r.acked_at, r.failed_at, r.reason)
        for r in run_a
    ]
    fields_b = [
        (r.id, r.session_id, r.text, r.seq, r.state, r.queued_at, r.delivered_at, r.acked_at, r.failed_at, r.reason)
        for r in run_b
    ]
    assert fields == fields_b
    # Sanity: the three terminal states are all represented.
    states = {r.state for r in run_a}
    assert states == {DeliveryState.ACKED, DeliveryState.FAILED}
    assert [r.state.value for r in run_a] == ["acked", "failed", "failed"]


# ---------------------------------------------------------------------------
# Real default channel (InboxChannel) is a working seam
# ---------------------------------------------------------------------------


def test_inbox_channel_default_delivers_and_drains():
    svc = _service()
    # No explicit channel -> service mints a real InboxChannel and returns it.
    channel = svc.register_session("s", None)
    assert isinstance(channel, InboxChannel)
    assert isinstance(channel, DeliveryChannel)

    r = svc.dispatch_reply("s", "look at the logs")
    assert r.state is DeliveryState.DELIVERED
    assert channel.pending() == 1

    # The session loop drains its inbox, applies the steer, then acks.
    envelopes = channel.drain()
    assert [e.text for e in envelopes] == ["look at the logs"]
    assert channel.pending() == 0
    svc.acknowledge(envelopes[0].receipt_id)
    assert svc.get_receipt(r.id).state is DeliveryState.ACKED
