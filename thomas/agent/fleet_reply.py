"""Inline reply / steer dispatch service for the fleet dashboard (CAP-040).

This is the backend *core* behind the dashboard's inline reply control: it
takes a free-text steer message typed against one running fleet session and
delivers it to that session, tracking the delivery through an explicit
acknowledgement state machine. The dashboard text-box UI (under
``thomas/server/web``) is a separate, peer-owned surface; it calls this service
and renders the receipts this service returns.

Model
-----
Sessions
    A running fleet session is *registered* with an id and an injectable
    :class:`DeliveryChannel`. Registration is the seam between "this session is
    alive and steerable" and "this session has ended": an unregistered (never
    seen, or ended) session id is a hard reject, never a silent drop.

Receipt state machine
    Every ``dispatch_reply`` mints a :class:`DeliveryReceipt` that walks a
    bounded state machine::

        QUEUED ──deliver ok──▶ DELIVERED ──ack──▶ ACKED   (terminal)
          │                        │
          └──deliver fail──▶ FAILED ◀──ack deadline──┘     (terminal)

    ``QUEUED``    the steer has been accepted and a receipt exists, but the
                  channel has not yet taken it.
    ``DELIVERED`` the channel accepted the envelope for the target session.
    ``ACKED``     the target session confirmed receipt (terminal success).
    ``FAILED``    the channel refused/errored, or the session never acked
                  before the deadline (terminal; ``undelivered`` distinguishes
                  "never delivered" from "delivered but unacknowledged").

    Transitions are validated: an out-of-order transition (e.g. acking an
    already-failed receipt) raises :class:`ReceiptStateError` instead of
    silently corrupting the receipt.

Ordering & determinism
    Receipts carry a monotonic ``seq`` assigned at dispatch, and their ids are
    derived from it (``rcpt-<seq>``), so :meth:`FleetReplyService.receipts`
    returns a stable, dispatch-ordered view and two runs of the same sequence
    against the same fake clock/channel produce byte-identical receipts. The
    ack deadline is a finite, injected bound; :meth:`FleetReplyService.reconcile`
    is a pure function of the receipts and the supplied ``now``.

Injectable edges
    * ``clock`` — a ``Callable[[], float]`` (defaults to ``time.monotonic``).
    * :class:`DeliveryChannel` — the per-session transport. The real default,
      :class:`InboxChannel`, is a stdlib in-process inbox the session's own
      loop drains; tests use a hermetic :class:`FakeChannel`.
"""

from __future__ import annotations

import dataclasses
import enum
import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# Concrete transport faults we treat as a delivery failure (not a crash). A
# channel talking to a websocket / queue / subprocess can raise any of these;
# we convert them into a FAILED receipt rather than letting one bad session
# take down a fleet-wide dispatch. This is a WIDE SPECIFIC tuple on purpose --
# a bare ``except Exception`` would hide real programming errors.
_CHANNEL_FAULTS: tuple[type[BaseException], ...] = (
    ConnectionError,
    TimeoutError,
    BrokenPipeError,
    OSError,
    RuntimeError,
    ValueError,
    KeyError,
    LookupError,
)

DEFAULT_ACK_DEADLINE_SECONDS: float = 30.0


class DeliveryState(str, enum.Enum):
    """Lifecycle states for a single dispatched steer message."""

    QUEUED = "queued"
    DELIVERED = "delivered"
    ACKED = "acked"
    FAILED = "failed"


# Allowed forward transitions. Anything not listed is a programmer/protocol
# error and raises ReceiptStateError.
_ALLOWED_TRANSITIONS: dict[DeliveryState, frozenset[DeliveryState]] = {
    DeliveryState.QUEUED: frozenset({DeliveryState.DELIVERED, DeliveryState.ACKED, DeliveryState.FAILED}),
    DeliveryState.DELIVERED: frozenset({DeliveryState.ACKED, DeliveryState.FAILED}),
    DeliveryState.ACKED: frozenset(),
    DeliveryState.FAILED: frozenset(),
}

_TERMINAL_STATES: frozenset[DeliveryState] = frozenset({DeliveryState.ACKED, DeliveryState.FAILED})


class FleetReplyError(Exception):
    """Base class for fleet-reply dispatch errors."""


class UnknownSessionError(FleetReplyError):
    """A reply was dispatched to a session that is not registered (unknown/ended)."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        super().__init__(f"no live fleet session registered for id {session_id!r}")


class UnknownReceiptError(FleetReplyError):
    """An ack/lookup referenced a receipt id that does not exist."""

    def __init__(self, receipt_id: str) -> None:
        self.receipt_id = receipt_id
        super().__init__(f"no delivery receipt with id {receipt_id!r}")


class ReceiptStateError(FleetReplyError):
    """An operation was attempted from an incompatible receipt state."""

    def __init__(self, receipt_id: str, current: DeliveryState, target: DeliveryState) -> None:
        self.receipt_id = receipt_id
        self.current = current
        self.target = target
        super().__init__(f"receipt {receipt_id!r} cannot move {current.value} -> {target.value}")


@dataclasses.dataclass(frozen=True)
class ReplyEnvelope:
    """The immutable steer payload handed to a :class:`DeliveryChannel`."""

    receipt_id: str
    session_id: str
    text: str
    seq: int
    created_at: float


@runtime_checkable
class DeliveryChannel(Protocol):
    """Transport for delivering a steer envelope to one running session.

    ``deliver`` returns ``True`` when the envelope was accepted for the target
    session and ``False`` for a clean refusal (e.g. the session's inbox is
    closed). Raising one of :data:`_CHANNEL_FAULTS` is treated as a delivery
    failure. ``deliver`` MUST NOT block indefinitely; the ack deadline governs
    the *acknowledgement*, not the transport call.
    """

    def deliver(self, envelope: ReplyEnvelope) -> bool: ...


@dataclasses.dataclass
class DeliveryReceipt:
    """Mutable record tracking one steer message through its state machine.

    A receipt is created ``QUEUED`` at dispatch and only ever moves forward
    through :data:`_ALLOWED_TRANSITIONS`. Timestamps are stamped from the
    injected clock as each state is entered.
    """

    id: str
    session_id: str
    text: str
    seq: int
    state: DeliveryState
    queued_at: float
    delivered_at: float | None = None
    acked_at: float | None = None
    failed_at: float | None = None
    reason: str | None = None
    undelivered: bool = False

    @property
    def is_terminal(self) -> bool:
        return self.state in _TERMINAL_STATES

    @property
    def is_acked(self) -> bool:
        return self.state is DeliveryState.ACKED

    @property
    def is_failed(self) -> bool:
        return self.state is DeliveryState.FAILED

    def snapshot(self) -> DeliveryReceipt:
        """A detached copy safe to hand to the UI/route layer."""
        return dataclasses.replace(self)


class InboxChannel:
    """Real default channel: an in-process inbox the session loop drains.

    The registered session's own runtime pulls envelopes via :meth:`drain`
    (or :meth:`pop`) and, once it has applied a steer, calls back into
    :meth:`FleetReplyService.acknowledge`. ``open`` gates delivery so a session
    that is winding down can cleanly refuse (``deliver`` -> ``False``) rather
    than silently swallowing steers.
    """

    def __init__(self, *, open: bool = True, maxlen: int | None = None) -> None:
        self._open = open
        self._inbox: deque[ReplyEnvelope] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    @property
    def open(self) -> bool:
        return self._open

    def close(self) -> None:
        with self._lock:
            self._open = False

    def deliver(self, envelope: ReplyEnvelope) -> bool:
        with self._lock:
            if not self._open:
                return False
            self._inbox.append(envelope)
            return True

    def drain(self) -> list[ReplyEnvelope]:
        """Remove and return every pending envelope in delivery order."""
        with self._lock:
            items = list(self._inbox)
            self._inbox.clear()
            return items

    def pop(self) -> ReplyEnvelope | None:
        with self._lock:
            if not self._inbox:
                return None
            return self._inbox.popleft()

    def pending(self) -> int:
        with self._lock:
            return len(self._inbox)


@dataclasses.dataclass(frozen=True)
class FleetReplyConfig:
    """Tunables for the reply service.

    ack_deadline_seconds: bounded wait, measured from dispatch, after which an
        un-acked (still QUEUED/DELIVERED) receipt is reconciled to FAILED and
        reported ``undelivered``.
    """

    ack_deadline_seconds: float = DEFAULT_ACK_DEADLINE_SECONDS


class FleetReplyService:
    """Register live fleet sessions and dispatch/track inline steer replies.

    Thread-safe: an ``RLock`` guards session registration and the receipt
    table. The external :meth:`DeliveryChannel.deliver` call is made *outside*
    the lock so a slow transport cannot stall unrelated dispatches.
    """

    def __init__(
        self,
        *,
        config: FleetReplyConfig | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.config = config or FleetReplyConfig()
        self._clock: Callable[[], float] = clock or time.monotonic
        self._sessions: dict[str, DeliveryChannel] = {}
        self._receipts: dict[str, DeliveryReceipt] = {}
        self._seq = 0
        self._lock = threading.RLock()

    # -- session registry ----------------------------------------------------

    def register_session(self, session_id: str, channel: DeliveryChannel | None = None) -> DeliveryChannel:
        """Register a running session and its delivery channel.

        With no channel supplied a fresh :class:`InboxChannel` is created and
        returned, so a caller that just wants "a steerable session" gets a
        working default. Re-registering an id replaces its channel.
        """
        if not session_id:
            raise ValueError("session_id must be a non-empty string")
        chan = channel if channel is not None else InboxChannel()
        with self._lock:
            self._sessions[session_id] = chan
        return chan

    def unregister_session(self, session_id: str) -> bool:
        """Mark a session ended. Returns True if it was registered.

        After this, any reply to ``session_id`` is rejected with
        :class:`UnknownSessionError` until it is registered again.
        """
        with self._lock:
            existed = self._sessions.pop(session_id, None) is not None
        return existed

    def is_registered(self, session_id: str) -> bool:
        with self._lock:
            return session_id in self._sessions

    def session_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._sessions.keys())

    # -- dispatch ------------------------------------------------------------

    def dispatch_reply(self, session_id: str, text: str) -> DeliveryReceipt:
        """Deliver a free-text steer to ``session_id`` and return its receipt.

        Rejects (raises :class:`UnknownSessionError`) an unknown/ended session
        instead of dropping the message. Empty/whitespace text is rejected with
        ``ValueError``. On success the receipt is QUEUED then transitions to
        DELIVERED (channel accepted) or FAILED (channel refused/errored).
        """
        if not isinstance(text, str) or not text.strip():
            raise ValueError("reply text must be a non-empty string")

        with self._lock:
            channel = self._sessions.get(session_id)
            if channel is None:
                raise UnknownSessionError(session_id)
            self._seq += 1
            seq = self._seq
            now = self._clock()
            receipt = DeliveryReceipt(
                id=f"rcpt-{seq}",
                session_id=session_id,
                text=text,
                seq=seq,
                state=DeliveryState.QUEUED,
                queued_at=now,
            )
            self._receipts[receipt.id] = receipt
            envelope = ReplyEnvelope(
                receipt_id=receipt.id,
                session_id=session_id,
                text=text,
                seq=seq,
                created_at=now,
            )

        # External transport call: made outside the lock on purpose.
        try:
            accepted = channel.deliver(envelope)
        except _CHANNEL_FAULTS as exc:
            logger.warning("fleet reply %s to session %s failed in channel: %r", receipt.id, session_id, exc)
            self._transition(receipt.id, DeliveryState.FAILED, reason=f"channel_error: {exc}", undelivered=True)
            return self._snapshot(receipt.id)

        if accepted:
            self._transition(receipt.id, DeliveryState.DELIVERED)
        else:
            self._transition(receipt.id, DeliveryState.FAILED, reason="channel_rejected", undelivered=True)
        return self._snapshot(receipt.id)

    # -- acknowledgement -----------------------------------------------------

    def acknowledge(self, receipt_id: str) -> DeliveryReceipt:
        """Reconcile a delivered receipt to ACKED (the session confirmed it).

        Acking an already-ACKED receipt is idempotent. Acking a FAILED receipt
        (e.g. one already timed out) raises :class:`ReceiptStateError` -- a late
        ack does not resurrect a bounded-out delivery.
        """
        with self._lock:
            receipt = self._receipts.get(receipt_id)
            if receipt is None:
                raise UnknownReceiptError(receipt_id)
            if receipt.state is DeliveryState.ACKED:
                return receipt.snapshot()
            self._apply_transition(receipt, DeliveryState.ACKED, acked_at=self._clock())
            return receipt.snapshot()

    # -- deadline reconciliation --------------------------------------------

    def reconcile(self, now: float | None = None) -> list[DeliveryReceipt]:
        """Fail every un-acked receipt whose ack deadline has elapsed.

        Deterministic and bounded: the deadline is measured from ``queued_at``
        (dispatch time) using the supplied ``now`` (or the injected clock).
        Returns snapshots of the receipts newly moved to FAILED, in seq order.
        """
        moment = self._clock() if now is None else now
        deadline = self.config.ack_deadline_seconds
        newly_failed: list[DeliveryReceipt] = []
        with self._lock:
            for receipt in sorted(self._receipts.values(), key=lambda r: r.seq):
                if receipt.state in _TERMINAL_STATES:
                    continue
                if moment - receipt.queued_at >= deadline:
                    self._apply_transition(
                        receipt,
                        DeliveryState.FAILED,
                        failed_at=moment,
                        reason="ack_timeout",
                        undelivered=True,
                    )
                    newly_failed.append(receipt.snapshot())
        return newly_failed

    # -- read views ----------------------------------------------------------

    def get_receipt(self, receipt_id: str) -> DeliveryReceipt:
        with self._lock:
            receipt = self._receipts.get(receipt_id)
            if receipt is None:
                raise UnknownReceiptError(receipt_id)
            return receipt.snapshot()

    def receipts(self, session_id: str | None = None) -> tuple[DeliveryReceipt, ...]:
        """All receipts (optionally for one session) in dispatch (seq) order."""
        with self._lock:
            items = sorted(self._receipts.values(), key=lambda r: r.seq)
            if session_id is not None:
                items = [r for r in items if r.session_id == session_id]
            return tuple(r.snapshot() for r in items)

    def pending_receipts(self) -> tuple[DeliveryReceipt, ...]:
        """Non-terminal receipts (QUEUED/DELIVERED) in seq order."""
        with self._lock:
            items = sorted(
                (r for r in self._receipts.values() if r.state not in _TERMINAL_STATES),
                key=lambda r: r.seq,
            )
            return tuple(r.snapshot() for r in items)

    # -- internal ------------------------------------------------------------

    def _transition(self, receipt_id: str, target: DeliveryState, **fields: object) -> None:
        with self._lock:
            receipt = self._receipts.get(receipt_id)
            if receipt is None:  # pragma: no cover - receipt is created before any transition
                raise UnknownReceiptError(receipt_id)
            self._apply_transition(receipt, target, **fields)

    def _apply_transition(self, receipt: DeliveryReceipt, target: DeliveryState, **fields: object) -> None:
        """Validate and apply a state change (caller holds the lock)."""
        allowed = _ALLOWED_TRANSITIONS.get(receipt.state, frozenset())
        if target not in allowed:
            raise ReceiptStateError(receipt.id, receipt.state, target)
        now = self._clock()
        receipt.state = target
        if target is DeliveryState.DELIVERED and receipt.delivered_at is None:
            receipt.delivered_at = fields.pop("delivered_at", now)  # type: ignore[assignment]
        elif target is DeliveryState.ACKED and receipt.acked_at is None:
            receipt.acked_at = fields.pop("acked_at", now)  # type: ignore[assignment]
        elif target is DeliveryState.FAILED and receipt.failed_at is None:
            receipt.failed_at = fields.pop("failed_at", now)  # type: ignore[assignment]
        # Remaining explicit fields (reason, undelivered, or an unused stamp).
        for key, value in fields.items():
            if key in {"delivered_at", "acked_at", "failed_at"}:
                continue
            setattr(receipt, key, value)

    def _snapshot(self, receipt_id: str) -> DeliveryReceipt:
        with self._lock:
            return self._receipts[receipt_id].snapshot()
