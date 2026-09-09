"""CAP-100 L2: supervised desktop backend with IPC, health-checked restart, clean shutdown.

Proves the exact acceptance line against a hermetic ``FakeHost`` (no real
process, no network, injected clock + injected sleep):

- the supervisor starts the backend and an initial health check passes;
- an IPC request round-trips a response, and an emitted event is delivered to a
  subscriber;
- a simulated crash triggers a supervised restart with bounded backoff, the
  restart counter increments, and it stops at the configured cap (no hot loop);
- clean shutdown stops the backend (graceful, then force after a timeout) and
  further IPC is refused;
- determinism: replaying the same scripted scenario yields identical records.

The real ``SubprocessHost`` (live lane) is intentionally not exercised.
"""

from __future__ import annotations

import json

import pytest

from thomas.tools.desktop_supervisor import (
    STATE_FAILED,
    STATE_RUNNING,
    STATE_SHUTDOWN,
    BackendEvent,
    BackendNotRunning,
    BackendSpec,
    DesktopSupervisor,
)


# ---------------------------------------------------------------------------
# Hermetic fake host: an in-process backend that speaks the JSON IPC protocol.
# ---------------------------------------------------------------------------
class FakeBackend:
    """In-memory backend channel. No real process; deterministic message queue."""

    def __init__(self, handler, *, ignore_terminate: bool = False):
        self._handler = handler
        self._ignore_terminate = ignore_terminate
        self._outbox: list[str] = []
        self._alive = True
        self.terminated = False
        self.killed = False

    # -- test controls --
    def crash(self) -> None:
        self._alive = False

    def emit(self, name: str, payload: object) -> None:
        self._outbox.append(json.dumps({"type": "event", "name": name, "payload": payload}))

    # -- BackendChannel protocol --
    def is_alive(self) -> bool:
        return self._alive

    def send(self, line: str) -> None:
        message = json.loads(line)
        if message.get("type") != "request":
            return
        result = self._handler(message.get("method"), message.get("params"))
        self._outbox.append(json.dumps({"type": "response", "id": message["id"], "result": result}))

    def receive(self, timeout: float):
        if self._outbox:
            return self._outbox.pop(0)
        return None

    def terminate(self) -> None:
        self.terminated = True
        if not self._ignore_terminate:
            self._alive = False

    def kill(self) -> None:
        self.killed = True
        self._alive = False


class FakeHost:
    """Spawns :class:`FakeBackend` instances and records each spawn."""

    def __init__(self, handler, *, ignore_terminate: bool = False):
        self._handler = handler
        self._ignore_terminate = ignore_terminate
        self.spawned: list[FakeBackend] = []

    def spawn(self, spec: BackendSpec) -> FakeBackend:
        backend = FakeBackend(self._handler, ignore_terminate=self._ignore_terminate)
        self.spawned.append(backend)
        return backend


class FakeClock:
    """Mutable injected clock; ``sleep`` advances it (no real waiting)."""

    def __init__(self, start: float = 100.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _echo_handler(method, params):
    if method == "__health__":
        return {"ok": True}
    if method == "echo":
        return {"echoed": params}
    return {"method": method, "params": params}


def _make_supervisor(host, clock, **overrides):
    kwargs = dict(
        clock=clock,
        sleep=clock.sleep,
        base_backoff=1.0,
        backoff_multiplier=2.0,
        max_backoff=10.0,
        max_restarts=3,
        shutdown_grace=2.0,
        shutdown_poll=0.5,
    )
    kwargs.update(overrides)
    return DesktopSupervisor(BackendSpec(name="app-backend"), host, **kwargs)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_start_runs_initial_health_check_that_passes():
    clock = FakeClock()
    sup = _make_supervisor(FakeHost(_echo_handler), clock)

    check = sup.start()

    assert sup.state == STATE_RUNNING
    assert check.healthy is True
    assert check.detail == "ok"


def test_ipc_request_round_trip_and_event_delivered_to_subscriber():
    clock = FakeClock()
    host = FakeHost(_echo_handler)
    sup = _make_supervisor(host, clock)
    sup.start()

    received: list[BackendEvent] = []
    sup.subscribe(received.append)

    # Request/response round-trip.
    result = sup.request("echo", {"value": 42})
    assert result == {"echoed": {"value": 42}}

    # Backend emits an event -> delivered to the subscriber on pump.
    host.spawned[-1].emit("progress", {"pct": 75})
    delivered = sup.pump_events()

    assert [e.name for e in delivered] == ["progress"]
    assert received and received[0].name == "progress"
    assert received[0].payload == {"pct": 75}
    assert received[0].seq == 1


def test_crash_triggers_supervised_restart_with_backoff_then_caps():
    clock = FakeClock()
    host = FakeHost(_echo_handler)
    sup = _make_supervisor(host, clock)
    sup.start()

    # --- restart #1: backoff = base * 2**0 = 1.0 ---
    host.spawned[-1].crash()
    crash1 = sup.check_health()
    assert crash1.healthy is False
    assert crash1.detail == "process_exited"
    assert sup.restart_count == 0  # not yet restarted, just scheduled

    # Before the backoff window elapses: still pending, no new backend.
    clock.advance(0.5)
    pending = sup.check_health()
    assert pending.detail == "pending"
    assert sup.restart_count == 0
    assert len(host.spawned) == 1

    # After the backoff window: restart fires, counter increments.
    clock.advance(0.5)  # now at crash_time + 1.0
    restarted = sup.check_health()
    assert restarted.healthy is True
    assert restarted.detail == "restarted"
    assert sup.restart_count == 1
    assert len(host.spawned) == 2
    assert sup.restart_records[-1].backoff_seconds == 1.0

    # --- restart #2 (backoff 2.0) and #3 (backoff 4.0) ---
    expected_backoffs = [2.0, 4.0]
    for expected in expected_backoffs:
        host.spawned[-1].crash()
        sup.check_health()  # observe crash, schedule
        clock.advance(expected)
        sup.check_health()  # perform restart
    assert sup.restart_count == 3
    assert [r.backoff_seconds for r in sup.restart_records] == [1.0, 2.0, 4.0]

    # --- 4th crash: cap reached -> FAILED, counter frozen, no hot loop ---
    host.spawned[-1].crash()
    gave_up = sup.check_health()
    assert gave_up.detail == "gave_up"
    assert sup.state == STATE_FAILED
    assert sup.restart_count == 3  # stopped at the cap
    # Further health checks do not spawn or increment.
    spawned_at_cap = len(host.spawned)
    clock.advance(100.0)
    sup.check_health()
    assert sup.restart_count == 3
    assert len(host.spawned) == spawned_at_cap


def test_clean_shutdown_graceful_then_ipc_refused():
    clock = FakeClock()
    host = FakeHost(_echo_handler)
    sup = _make_supervisor(host, clock)
    sup.start()
    backend = host.spawned[-1]

    forced = sup.shutdown()

    assert forced is False  # graceful backend exits on terminate
    assert backend.terminated is True
    assert backend.killed is False
    assert sup.state == STATE_SHUTDOWN
    with pytest.raises(BackendNotRunning):
        sup.request("echo", {"value": 1})


def test_shutdown_force_kills_after_timeout():
    clock = FakeClock()
    host = FakeHost(_echo_handler, ignore_terminate=True)  # backend ignores graceful stop
    sup = _make_supervisor(host, clock)
    sup.start()
    backend = host.spawned[-1]

    forced = sup.shutdown()

    assert forced is True
    assert backend.terminated is True
    assert backend.killed is True
    assert sup.state == STATE_SHUTDOWN


def _run_scenario():
    clock = FakeClock()
    host = FakeHost(_echo_handler)
    sup = _make_supervisor(host, clock)
    sup.start()
    events: list[BackendEvent] = []
    sup.subscribe(events.append)
    sup.request("echo", {"n": 1})
    host.spawned[-1].emit("tick", {"i": 0})
    sup.pump_events()
    # crash + restart cycle
    host.spawned[-1].crash()
    sup.check_health()
    clock.advance(1.0)
    sup.check_health()
    return sup, events


def test_determinism_identical_replays():
    sup_a, events_a = _run_scenario()
    sup_b, events_b = _run_scenario()

    assert sup_a.restart_records == sup_b.restart_records
    assert sup_a.health_history == sup_b.health_history
    assert [(e.name, e.payload, e.seq) for e in events_a] == [(e.name, e.payload, e.seq) for e in events_b]
