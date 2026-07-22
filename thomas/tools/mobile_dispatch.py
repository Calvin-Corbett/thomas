"""CAP-103 hermetic core: dispatch a task to a registered mobile device and
reconcile its delivery/result state with bounded retry.

This module is the capability *minus* the physical push runtime. It provides:

1. A **device registry** -- register/lookup a device by ``device_id`` plus the
   platform push token used to reach it.
2. A **dispatch state machine** -- ``queued -> delivered -> acked ->
   completed | failed`` -- driving a task to a registered device over an
   **injectable** :class:`DeviceChannel`.
3. **Reconciliation** -- folding a device-reported ack and result back into the
   task's state.
4. **Bounded retry** -- if a dispatched task is not acked before its deadline,
   the task is re-sent over the channel up to ``retry_cap`` times, after which
   it is moved to the ``failed`` terminal state (never silently abandoned).

Everything is deterministic: the wall clock is an **injected callable** and the
device edge is an **injected channel**, so the same sequence of operations
always produces the same state history. Tests drive a hermetic
:class:`FakeChannel`; production uses :class:`PushServiceChannel`, whose live
lane targets a real APNs/FCM-style HTTP push endpoint via ``urllib`` (stdlib
only, no new dependencies).

Live lane (NOT exercised by the hermetic tests -- see
:class:`PushServiceChannel`): a real run needs valid APNs/FCM provider
credentials (an auth token / provider key), the provider's HTTPS push endpoint,
and a physical device that has registered a push token and runs a companion app
that acks and reports the task result. Nothing here claims such a live run has
happened; only the physical provisioning is gated.

Tools-layer rule: standard library only -- no imports from agent/server/cli.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# -- Dispatch states -------------------------------------------------------
STATE_QUEUED = "queued"
STATE_DELIVERED = "delivered"
STATE_ACKED = "acked"
STATE_COMPLETED = "completed"
STATE_FAILED = "failed"

_TERMINAL_STATES = frozenset({STATE_COMPLETED, STATE_FAILED})

# States from which the task is still "in flight" and subject to a deadline:
# either it was queued but the channel has not accepted delivery, or it was
# delivered but the device has not acked yet.
_PENDING_STATES = frozenset({STATE_QUEUED, STATE_DELIVERED})


class UnknownDeviceError(KeyError):
    """Raised when a dispatch targets a ``device_id`` that is not registered.

    Dispatch to an unknown device is *rejected*, never silently dropped.
    """


class TaskStateError(RuntimeError):
    """Raised when an operation is invalid for a task's current state."""


@dataclass(frozen=True)
class Device:
    """A registered mobile device reachable via a platform push token."""

    device_id: str
    push_token: str
    platform: str = "ios"


@dataclass(frozen=True)
class DeliveryReceipt:
    """Result of a single channel send attempt.

    Attributes:
        delivered: Whether the channel accepted the payload for delivery.
        provider_message_id: Provider-assigned id for the accepted push, if any.
        detail: Human-readable detail (e.g. an error reason on failure).
    """

    delivered: bool
    provider_message_id: str | None = None
    detail: str = ""


@dataclass(frozen=True)
class Transition:
    """One recorded state change in a task's lifecycle."""

    at: float
    from_state: str
    to_state: str
    reason: str


@dataclass
class TaskRecord:
    """A dispatched task and its full delivery/result lifecycle."""

    task_id: str
    device_id: str
    payload: dict
    state: str
    created_at: float
    updated_at: float
    deadline: float | None = None
    retry_count: int = 0
    result: dict | None = None
    receipts: list[DeliveryReceipt] = field(default_factory=list)
    history: list[Transition] = field(default_factory=list)

    @property
    def is_terminal(self) -> bool:
        return self.state in _TERMINAL_STATES


@runtime_checkable
class DeviceChannel(Protocol):
    """The injectable device edge: hand a payload to a device's push token.

    Implementations MUST NOT raise for ordinary delivery failures; they return
    ``DeliveryReceipt(delivered=False, ...)`` so the dispatch service can apply
    its bounded-retry policy uniformly.
    """

    def send(self, device: Device, task_id: str, payload: dict) -> DeliveryReceipt:
        """Attempt to deliver ``payload`` for ``task_id`` to ``device``."""
        ...


class FakeChannel:
    """Hermetic in-memory channel for tests -- no network, fully deterministic.

    By default every send is delivered. ``fail_tokens`` lists push tokens whose
    sends fail (to exercise delivery-retry), and ``fail_first`` maps a push
    token to a count of leading sends that fail before subsequent ones succeed
    (to exercise recover-on-retry). Every send is recorded in :attr:`sent`.
    """

    def __init__(
        self,
        *,
        fail_tokens: set[str] | None = None,
        fail_first: dict[str, int] | None = None,
    ) -> None:
        self.fail_tokens = set(fail_tokens or set())
        self.fail_first = dict(fail_first or {})
        self.sent: list[tuple[str, str, dict]] = []
        self._counts: dict[str, int] = {}

    def send(self, device: Device, task_id: str, payload: dict) -> DeliveryReceipt:
        self.sent.append((device.push_token, task_id, dict(payload)))
        n = self._counts.get(device.push_token, 0)
        self._counts[device.push_token] = n + 1
        if device.push_token in self.fail_tokens:
            return DeliveryReceipt(delivered=False, detail="fake: token marked failing")
        if n < self.fail_first.get(device.push_token, 0):
            return DeliveryReceipt(delivered=False, detail=f"fake: transient failure {n + 1}")
        seq = len(self.sent)
        return DeliveryReceipt(delivered=True, provider_message_id=f"fake-{seq}")


class PushServiceChannel:
    """Real default channel: POST the task payload to an APNs/FCM-style push
    endpoint over HTTPS using ``urllib`` (stdlib only).

    LIVE LANE -- not exercised by the hermetic test suite. A real dispatch needs:

    * ``endpoint`` -- the provider's push HTTPS URL (e.g. the APNs
      ``/3/device/<token>`` host, or the FCM send endpoint).
    * ``auth_token`` -- a valid provider credential (APNs JWT / provider key,
      or an FCM server/OAuth token) sent as a bearer ``Authorization`` header.
    * A **physical device** that has registered the ``push_token`` and runs a
      companion app which receives the push, acks receipt, and later reports the
      task result back (both reconciled via
      :meth:`MobileDispatchService.reconcile_ack` /
      :meth:`~MobileDispatchService.reconcile_result`).

    Without those, ``send`` returns ``delivered=False``. This class does not and
    cannot prove a live push happened; it is the honest production edge behind
    the injectable seam.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        auth_token: str | None = None,
        timeout: float = 10.0,
        opener: Callable[[urllib.request.Request, float], object] | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.auth_token = auth_token
        self.timeout = timeout
        # Injectable opener keeps even this class unit-testable without a socket;
        # defaults to the real stdlib urlopen for the live lane.
        self._opener = opener or (lambda req, timeout: urllib.request.urlopen(req, timeout=timeout))

    def send(self, device: Device, task_id: str, payload: dict) -> DeliveryReceipt:
        body = json.dumps(
            {
                "token": device.push_token,
                "platform": device.platform,
                "task_id": task_id,
                "payload": payload,
            }
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        request = urllib.request.Request(self.endpoint, data=body, headers=headers, method="POST")
        try:
            response = self._opener(request, self.timeout)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            # Ordinary delivery failure (unreachable provider, timeout, refused).
            # Concrete, narrow tuple -- surfaced to the retry policy, not swallowed.
            logger.warning("push delivery to %s failed: %s", device.device_id, exc)
            return DeliveryReceipt(delivered=False, detail=f"push error: {exc}")
        status = getattr(response, "status", None)
        message_id = None
        read = getattr(response, "read", None)
        if callable(read):
            try:
                raw = read()
                if raw:
                    message_id = json.loads(raw.decode("utf-8")).get("message_id")
            except (ValueError, UnicodeDecodeError) as exc:
                logger.debug("push response body not JSON for %s: %s", device.device_id, exc)
        delivered = status is None or 200 <= int(status) < 300
        return DeliveryReceipt(delivered=delivered, provider_message_id=message_id, detail=f"http {status}")


class MobileDispatchService:
    """Registry + dispatch state machine + bounded retry over an injected edge.

    Args:
        channel: The injectable :class:`DeviceChannel` used to reach devices.
        clock: A zero-arg callable returning the current time in seconds
            (injected for determinism; e.g. ``time.monotonic`` in production).
        ack_deadline_s: Seconds a task may sit pending (queued/delivered but not
            acked) before it becomes eligible for retry.
        retry_cap: Maximum number of re-sends after the initial dispatch. Once a
            task has been retried ``retry_cap`` times and still has not acked by
            its deadline, it is moved to ``failed``.
        id_factory: Optional deterministic task-id generator; defaults to a
            monotonically increasing ``task-<n>`` counter.
    """

    def __init__(
        self,
        channel: DeviceChannel,
        *,
        clock: Callable[[], float],
        ack_deadline_s: float = 30.0,
        retry_cap: int = 2,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        if ack_deadline_s <= 0:
            raise ValueError("ack_deadline_s must be positive")
        if retry_cap < 0:
            raise ValueError("retry_cap must be non-negative")
        self._channel = channel
        self._clock = clock
        self._ack_deadline_s = float(ack_deadline_s)
        self._retry_cap = int(retry_cap)
        self._devices: dict[str, Device] = {}
        self._tasks: dict[str, TaskRecord] = {}
        self._seq = 0
        self._id_factory = id_factory or self._default_id

    # -- device registry ----------------------------------------------------
    def register_device(self, device_id: str, push_token: str, platform: str = "ios") -> Device:
        """Register (or re-register) a device by id + push token."""
        if not device_id or not push_token:
            raise ValueError("device_id and push_token are required")
        device = Device(device_id=device_id, push_token=push_token, platform=platform)
        self._devices[device_id] = device
        return device

    def lookup_device(self, device_id: str) -> Device | None:
        """Return the registered device, or ``None`` if unknown."""
        return self._devices.get(device_id)

    # -- dispatch -----------------------------------------------------------
    def dispatch(self, device_id: str, payload: dict) -> TaskRecord:
        """Dispatch a task to a registered device, sending over the channel.

        Raises:
            UnknownDeviceError: If ``device_id`` is not registered. The dispatch
                is rejected -- the task is not created or silently dropped.
        """
        device = self._devices.get(device_id)
        if device is None:
            raise UnknownDeviceError(f"device '{device_id}' is not registered")

        now = self._clock()
        task = TaskRecord(
            task_id=self._id_factory(),
            device_id=device_id,
            payload=dict(payload),
            state=STATE_QUEUED,
            created_at=now,
            updated_at=now,
            deadline=now + self._ack_deadline_s,
        )
        self._tasks[task.task_id] = task
        self._attempt_send(task, device, reason="dispatch")
        return task

    # -- reconciliation -----------------------------------------------------
    def reconcile_ack(self, task_id: str) -> TaskRecord:
        """Fold a device-reported receipt ack into state (delivered -> acked)."""
        task = self._require_task(task_id)
        if task.state != STATE_DELIVERED:
            raise TaskStateError(f"cannot ack task in state '{task.state}' (expected '{STATE_DELIVERED}')")
        # Once acked, the task is no longer subject to the no-ack retry deadline.
        task.deadline = None
        self._transition(task, STATE_ACKED, reason="device ack")
        return task

    def reconcile_result(self, task_id: str, *, success: bool, result: dict | None = None) -> TaskRecord:
        """Fold a device-reported result into a terminal state.

        A success reconciles to ``completed``; a failure to ``failed``. Valid
        once the task has been delivered (an implicit ack is recorded if the
        device reports a result before an explicit ack).
        """
        task = self._require_task(task_id)
        if task.state not in (STATE_DELIVERED, STATE_ACKED):
            raise TaskStateError(
                f"cannot reconcile result for task in state '{task.state}' "
                f"(expected '{STATE_DELIVERED}' or '{STATE_ACKED}')"
            )
        task.deadline = None
        task.result = dict(result) if result is not None else None
        if task.state == STATE_DELIVERED:
            # Device reported a result without a prior explicit ack.
            self._transition(task, STATE_ACKED, reason="implicit ack via result")
        target = STATE_COMPLETED if success else STATE_FAILED
        self._transition(task, target, reason="device result: " + ("success" if success else "failure"))
        return task

    def reconcile_deadlines(self) -> list[TaskRecord]:
        """Apply the retry/fail policy to every task past its ack deadline.

        For each pending task whose deadline has elapsed: if it is still under
        the retry cap, re-send it over the channel and extend the deadline;
        otherwise move it to the ``failed`` terminal state. Returns the tasks
        that were acted on (retried or failed) this pass.
        """
        now = self._clock()
        acted: list[TaskRecord] = []
        for task in self._tasks.values():
            if task.state not in _PENDING_STATES:
                continue
            if task.deadline is None or now < task.deadline:
                continue
            device = self._devices.get(task.device_id)
            if device is None:
                # Device was deregistered after dispatch; fail rather than loop.
                self._transition(task, STATE_FAILED, reason="device no longer registered")
                acted.append(task)
                continue
            if task.retry_count >= self._retry_cap:
                self._transition(
                    task,
                    STATE_FAILED,
                    reason=f"no ack after {task.retry_count} retries (retry cap reached)",
                )
                acted.append(task)
                continue
            task.retry_count += 1
            task.deadline = now + self._ack_deadline_s
            self._attempt_send(task, device, reason=f"retry {task.retry_count}")
            acted.append(task)
        return acted

    # -- accessors ----------------------------------------------------------
    def get_task(self, task_id: str) -> TaskRecord:
        """Return the task record, raising ``KeyError`` if unknown."""
        return self._require_task(task_id)

    def tasks(self) -> list[TaskRecord]:
        """Return all task records in dispatch order."""
        return list(self._tasks.values())

    # -- internals ----------------------------------------------------------
    def _attempt_send(self, task: TaskRecord, device: Device, *, reason: str) -> None:
        receipt = self._channel.send(device, task.task_id, task.payload)
        task.receipts.append(receipt)
        if receipt.delivered:
            self._transition(task, STATE_DELIVERED, reason=f"{reason}: delivered")
        else:
            # Stay pending (queued) with the deadline set; retry policy handles it.
            self._touch(task)

    def _transition(self, task: TaskRecord, to_state: str, *, reason: str) -> None:
        now = self._clock()
        task.history.append(Transition(at=now, from_state=task.state, to_state=to_state, reason=reason))
        task.state = to_state
        task.updated_at = now

    def _touch(self, task: TaskRecord) -> None:
        task.updated_at = self._clock()

    def _require_task(self, task_id: str) -> TaskRecord:
        task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(f"unknown task '{task_id}'")
        return task

    def _default_id(self) -> str:
        self._seq += 1
        return f"task-{self._seq}"
