"""CAP-100 L2: supervised desktop-app backend with IPC, health-checked restart, clean shutdown.

This module is the *hermetic core* of a Tauri/Electron-style desktop app's
backend supervisor. A desktop app is a GUI frontend (webview) driving a
long-lived backend process; that backend must be started, kept alive across
crashes, talked to over an IPC channel, and shut down cleanly. Everything here
is the capability **minus the physical GUI runtime**:

* **Lifecycle + health checks.** :class:`DesktopSupervisor.start` spawns the
  backend through an injected :class:`ProcessHost` and runs an initial health
  check. :meth:`DesktopSupervisor.check_health` performs one periodic probe
  (process liveness + an IPC health round-trip).
* **IPC request/response + event stream.** :meth:`DesktopSupervisor.request`
  performs a JSON request/response round-trip over the backend channel.
  Backends also push *events* (frontend-bound notifications); subscribers
  registered via :meth:`DesktopSupervisor.subscribe` receive every delivered
  event, drained by :meth:`DesktopSupervisor.pump_events`.
* **Supervised restart.** A crash observed by a health check triggers a
  restart scheduled after a *bounded exponential backoff*. Restarts are capped
  (:attr:`max_restarts`); once the cap is hit the supervisor enters ``FAILED``
  rather than hot-looping. Every restart is recorded as a :class:`RestartRecord`.
* **Clean shutdown.** :meth:`DesktopSupervisor.shutdown` sends a graceful stop,
  waits up to ``shutdown_grace`` seconds, then force-kills if the backend is
  still alive. After shutdown (or failure) any further IPC is refused.

Determinism / hermeticity: the supervisor takes an **injected clock** and an
**injected sleep** (both zero/one-arg callables), and drives the backend
exclusively through the injected host. The real default host
(:class:`SubprocessHost`) spawns a backend via stdlib :mod:`subprocess` and
frames newline-delimited JSON over its stdio -- that is the **live lane** and
is never exercised in tests. Tests use :class:`FakeHost`, so behaviour is fully
reproducible with no real processes, sleeps, or network.

Live lane (honest): :class:`SubprocessHost` needs a *real* backend executable --
i.e. a built Tauri/Electron sidecar (or any process that speaks the
newline-delimited JSON IPC protocol on stdin/stdout) -- plus, for a real desktop
app, a GUI host to attach the webview frontend to. None of that is provisioned
here; the SPI, protocol, and policy are.

Depends only on the standard library (tools-tier rule: no imports from
``agent``/``server``/``cli``).
"""

from __future__ import annotations

import json
import logging
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable, Protocol

logger = logging.getLogger(__name__)

ClockFn = Callable[[], float]
SleepFn = Callable[[float], None]
EventSubscriber = Callable[["BackendEvent"], None]

# -- IPC message framing ----------------------------------------------------
MSG_TYPE = "type"
MSG_REQUEST = "request"
MSG_RESPONSE = "response"
MSG_EVENT = "event"
HEALTH_METHOD = "__health__"

# -- Supervisor lifecycle states --------------------------------------------
STATE_STOPPED = "stopped"
STATE_RUNNING = "running"
STATE_RESTART_PENDING = "restart_pending"
STATE_FAILED = "failed"
STATE_SHUTDOWN = "shutdown"


class SupervisorError(Exception):
    """Base class for supervisor faults."""


class BackendNotRunning(SupervisorError):
    """Raised when IPC is attempted while no backend is running."""


class IpcError(SupervisorError):
    """Raised on an IPC protocol violation or a request timeout."""


@dataclass(frozen=True)
class BackendSpec:
    """How to launch a backend process.

    Attributes:
        name: Human-readable backend name (used in logs/records).
        command: Argv list for the real host to spawn (live lane only).
        cwd: Working directory for the spawned process.
        env: Environment overrides for the spawned process.
    """

    name: str
    command: tuple[str, ...] = ()
    cwd: str | None = None
    env: dict[str, str] | None = None


@dataclass(frozen=True)
class BackendEvent:
    """A frontend-bound notification pushed by the backend.

    Attributes:
        name: Event name (e.g. ``"progress"``).
        payload: Arbitrary JSON-serialisable payload.
        seq: Monotonic per-supervisor delivery sequence number.
    """

    name: str
    payload: object
    seq: int


@dataclass(frozen=True)
class RestartRecord:
    """Evidence for one supervised restart.

    Attributes:
        index: 1-based restart counter value after this restart.
        crashed_at: Clock value when the crash was observed.
        restarted_at: Clock value when the restart completed.
        backoff_seconds: Backoff window applied before this restart.
    """

    index: int
    crashed_at: float
    restarted_at: float
    backoff_seconds: float


@dataclass(frozen=True)
class HealthCheck:
    """Result of one health probe.

    Attributes:
        at: Clock value when the probe ran.
        healthy: Whether the backend answered a health round-trip while alive.
        detail: Short reason string (``"ok"``, ``"process_exited"``,
            ``"probe_timeout"``, ``"pending"``, ``"restarted"``, ``"gave_up"``).
    """

    at: float
    healthy: bool
    detail: str


# ---------------------------------------------------------------------------
# Process host SPI -- the injectable runtime edge.
# ---------------------------------------------------------------------------
class BackendChannel(Protocol):
    """A live handle to one backend process + its IPC byte stream."""

    def is_alive(self) -> bool:
        """Return ``True`` while the backend process is still running."""

    def send(self, line: str) -> None:
        """Write one framed message line to the backend's input stream."""

    def receive(self, timeout: float) -> str | None:
        """Read one framed message line, or ``None`` if none arrived in time."""

    def terminate(self) -> None:
        """Ask the backend to stop gracefully (SIGTERM / stdin close)."""

    def kill(self) -> None:
        """Force-kill the backend process tree."""


class ProcessHost(Protocol):
    """Factory that spawns backend processes. The injectable runtime edge."""

    def spawn(self, spec: BackendSpec) -> BackendChannel:
        """Launch a backend for ``spec`` and return a live channel to it."""


# ---------------------------------------------------------------------------
# Real (live-lane) host -- NOT exercised in tests.
# ---------------------------------------------------------------------------
class _SubprocessChannel:
    """Newline-delimited JSON IPC over a real child process's stdio.

    LIVE LANE: this talks to a real process and is not used in hermetic tests.
    A background reader thread drains stdout into a queue so :meth:`receive`
    can honour a timeout without blocking the supervisor.
    """

    def __init__(self, proc: subprocess.Popen[str], name: str) -> None:
        self._proc = proc
        self._name = name
        self._inbox: queue.Queue[str] = queue.Queue()
        self._reader = threading.Thread(target=self._drain_stdout, name=f"desktop-ipc-{name}", daemon=True)
        self._reader.start()

    def _drain_stdout(self) -> None:
        stdout = self._proc.stdout
        if stdout is None:
            return
        try:
            for line in stdout:
                self._inbox.put(line.rstrip("\n"))
        except (ValueError, OSError) as exc:
            logger.warning("desktop backend %s stdout reader stopped: %s", self._name, exc)

    def is_alive(self) -> bool:
        return self._proc.poll() is None

    def send(self, line: str) -> None:
        stdin = self._proc.stdin
        if stdin is None:
            raise IpcError("backend stdin is not writable")
        try:
            stdin.write(line + "\n")
            stdin.flush()
        except (BrokenPipeError, ValueError, OSError) as exc:
            raise IpcError(f"failed writing to backend {self._name}: {exc}") from exc

    def receive(self, timeout: float) -> str | None:
        try:
            return self._inbox.get(timeout=max(0.0, timeout))
        except queue.Empty:
            return None

    def terminate(self) -> None:
        stdin = self._proc.stdin
        if stdin is not None:
            try:
                stdin.close()
            except (ValueError, OSError) as exc:
                logger.debug("closing stdin for %s failed: %s", self._name, exc)
        try:
            self._proc.terminate()
        except (ProcessLookupError, OSError) as exc:
            logger.debug("terminate for %s failed: %s", self._name, exc)

    def kill(self) -> None:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(self._proc.pid)],
                capture_output=True,
                check=False,
            )
            return
        try:
            self._proc.kill()
        except (ProcessLookupError, OSError) as exc:
            logger.debug("kill for %s failed: %s", self._name, exc)


class SubprocessHost:
    """Real :class:`ProcessHost` that spawns a backend via :mod:`subprocess`.

    LIVE LANE. Requires a real backend executable (a built Tauri/Electron
    sidecar, or any process that reads JSON request lines on stdin and writes
    JSON response/event lines on stdout). Never spawned in the test suite.
    """

    def spawn(self, spec: BackendSpec) -> BackendChannel:
        if not spec.command:
            raise SupervisorError(f"backend {spec.name!r} has no command to spawn")
        try:
            proc = subprocess.Popen(
                list(spec.command),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                cwd=spec.cwd,
                env=spec.env,
                text=True,
                bufsize=1,
            )
        except (OSError, ValueError) as exc:
            raise SupervisorError(f"failed to spawn backend {spec.name!r}: {exc}") from exc
        return _SubprocessChannel(proc, spec.name)


# ---------------------------------------------------------------------------
# The supervisor.
# ---------------------------------------------------------------------------
class DesktopSupervisor:
    """Supervises a desktop-app backend: lifecycle, IPC, restart, shutdown."""

    def __init__(
        self,
        spec: BackendSpec,
        host: ProcessHost,
        *,
        clock: ClockFn = time.monotonic,
        sleep: SleepFn = time.sleep,
        request_timeout: float = 5.0,
        health_timeout: float = 2.0,
        base_backoff: float = 0.5,
        backoff_multiplier: float = 2.0,
        max_backoff: float = 30.0,
        max_restarts: int = 3,
        shutdown_grace: float = 5.0,
        shutdown_poll: float = 0.1,
    ) -> None:
        if max_restarts < 0:
            raise ValueError("max_restarts must be >= 0")
        if base_backoff < 0 or max_backoff < 0:
            raise ValueError("backoff values must be >= 0")
        self.spec = spec
        self.host = host
        self._clock = clock
        self._sleep = sleep
        self.request_timeout = request_timeout
        self.health_timeout = health_timeout
        self.base_backoff = base_backoff
        self.backoff_multiplier = backoff_multiplier
        self.max_backoff = max_backoff
        self.max_restarts = max_restarts
        self.shutdown_grace = shutdown_grace
        self.shutdown_poll = shutdown_poll

        self.state = STATE_STOPPED
        self.restart_count = 0
        self.restart_records: list[RestartRecord] = []
        self.health_history: list[HealthCheck] = []

        self._channel: BackendChannel | None = None
        self._next_request_id = 1
        self._event_seq = 0
        self._subscribers: list[EventSubscriber] = []
        self._crashed_at: float | None = None
        self._restart_due_at: float | None = None
        self._pending_backoff: float = 0.0

    # -- lifecycle ----------------------------------------------------------
    def start(self) -> HealthCheck:
        """Spawn the backend and run an initial health check.

        Returns the initial :class:`HealthCheck`. Raises :class:`SupervisorError`
        if the backend cannot be spawned.
        """
        if self.state not in (STATE_STOPPED,):
            raise SupervisorError(f"cannot start from state {self.state!r}")
        self._channel = self.host.spawn(self.spec)
        self.state = STATE_RUNNING
        logger.info("desktop backend %s started", self.spec.name)
        return self.check_health()

    def subscribe(self, callback: EventSubscriber) -> None:
        """Register ``callback`` to receive every delivered :class:`BackendEvent`."""
        self._subscribers.append(callback)

    # -- IPC ----------------------------------------------------------------
    def request(self, method: str, params: object = None) -> object:
        """Perform an IPC request/response round-trip and return the result.

        Raises :class:`BackendNotRunning` if no backend is running (including
        after shutdown), and :class:`IpcError` on timeout or protocol error.
        """
        if self.state != STATE_RUNNING or self._channel is None:
            raise BackendNotRunning(f"backend not running (state={self.state})")
        return self._request_on(self._channel, method, params, self.request_timeout)

    def _request_on(self, channel: BackendChannel, method: str, params: object, timeout: float) -> object:
        request_id = self._next_request_id
        self._next_request_id += 1
        line = json.dumps({MSG_TYPE: MSG_REQUEST, "id": request_id, "method": method, "params": params})
        channel.send(line)
        deadline = self._clock() + timeout
        while True:
            remaining = deadline - self._clock()
            if remaining < 0:
                raise IpcError(f"IPC request {method!r} timed out")
            raw = channel.receive(remaining)
            if raw is None:
                raise IpcError(f"IPC request {method!r} timed out")
            message = self._decode(raw)
            if message is None:
                continue
            kind = message.get(MSG_TYPE)
            if kind == MSG_EVENT:
                self._dispatch_event(message)
            elif kind == MSG_RESPONSE and message.get("id") == request_id:
                if "error" in message and message["error"] is not None:
                    raise IpcError(f"backend error for {method!r}: {message['error']}")
                return message.get("result")
            # Unrelated responses/messages are ignored.

    def pump_events(self) -> list[BackendEvent]:
        """Drain any backend-pushed events and deliver them to subscribers.

        Returns the events delivered during this pump, in order.
        """
        if self.state != STATE_RUNNING or self._channel is None:
            return []
        delivered: list[BackendEvent] = []
        while True:
            raw = self._channel.receive(0.0)
            if raw is None:
                break
            message = self._decode(raw)
            if message is None:
                continue
            if message.get(MSG_TYPE) == MSG_EVENT:
                delivered.append(self._dispatch_event(message))
        return delivered

    def _dispatch_event(self, message: dict[str, object]) -> BackendEvent:
        self._event_seq += 1
        event = BackendEvent(
            name=str(message.get("name", "")),
            payload=message.get("payload"),
            seq=self._event_seq,
        )
        for subscriber in list(self._subscribers):
            subscriber(event)
        return event

    @staticmethod
    def _decode(raw: str) -> dict[str, object] | None:
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("dropping malformed IPC line: %s", exc)
            return None
        if not isinstance(value, dict):
            logger.warning("dropping non-object IPC message: %r", raw)
            return None
        return value

    # -- health + supervised restart ---------------------------------------
    def check_health(self) -> HealthCheck:
        """Run one periodic health check, driving restart scheduling.

        Behaviour by state:

        * ``RUNNING`` -- probe process liveness then an IPC health round-trip;
          on failure, schedule a supervised restart (or give up at the cap).
        * ``RESTART_PENDING`` -- if the backoff window has elapsed, perform the
          restart; otherwise stay pending.
        * ``FAILED`` / ``SHUTDOWN`` / ``STOPPED`` -- report unhealthy without
          probing.
        """
        now = self._clock()
        if self.state == STATE_RESTART_PENDING:
            return self._maybe_restart(now)
        if self.state != STATE_RUNNING or self._channel is None:
            return self._record_health(now, False, self.state)

        if not self._channel.is_alive():
            return self._on_crash(now, "process_exited")
        try:
            self._request_on(self._channel, HEALTH_METHOD, None, self.health_timeout)
        except IpcError as exc:
            logger.warning("health probe for %s failed: %s", self.spec.name, exc)
            return self._on_crash(now, "probe_timeout")
        return self._record_health(now, True, "ok")

    def _on_crash(self, now: float, reason: str) -> HealthCheck:
        logger.warning("desktop backend %s crash observed: %s", self.spec.name, reason)
        if self.restart_count >= self.max_restarts:
            self.state = STATE_FAILED
            self._channel = None
            logger.error(
                "desktop backend %s exceeded restart cap (%d); giving up",
                self.spec.name,
                self.max_restarts,
            )
            return self._record_health(now, False, "gave_up")
        self._crashed_at = now
        self._pending_backoff = self._backoff_for(self.restart_count + 1)
        self._restart_due_at = now + self._pending_backoff
        self.state = STATE_RESTART_PENDING
        self._channel = None
        return self._record_health(now, False, reason)

    def _maybe_restart(self, now: float) -> HealthCheck:
        if self._restart_due_at is None or now < self._restart_due_at:
            return self._record_health(now, False, "pending")
        self._channel = self.host.spawn(self.spec)
        self.restart_count += 1
        self.restart_records.append(
            RestartRecord(
                index=self.restart_count,
                crashed_at=self._crashed_at if self._crashed_at is not None else now,
                restarted_at=now,
                backoff_seconds=self._pending_backoff,
            )
        )
        self.state = STATE_RUNNING
        self._crashed_at = None
        self._restart_due_at = None
        logger.info("desktop backend %s restarted (restart #%d)", self.spec.name, self.restart_count)
        return self._record_health(now, True, "restarted")

    def _backoff_for(self, attempt_index: int) -> float:
        raw = self.base_backoff * (self.backoff_multiplier ** (attempt_index - 1))
        return min(raw, self.max_backoff)

    def _record_health(self, at: float, healthy: bool, detail: str) -> HealthCheck:
        check = HealthCheck(at=at, healthy=healthy, detail=detail)
        self.health_history.append(check)
        return check

    # -- shutdown -----------------------------------------------------------
    def shutdown(self) -> bool:
        """Stop the backend cleanly: graceful terminate, then force-kill on timeout.

        Returns ``True`` if a force-kill was required, ``False`` if the backend
        stopped gracefully. Idempotent after the first call. Further IPC is
        refused once shutdown completes.
        """
        if self.state in (STATE_SHUTDOWN, STATE_STOPPED, STATE_FAILED):
            self.state = STATE_SHUTDOWN
            return False
        channel = self._channel
        self.state = STATE_SHUTDOWN
        self._channel = None
        if channel is None:
            return False
        channel.terminate()
        waited = 0.0
        forced = False
        while waited < self.shutdown_grace:
            if not channel.is_alive():
                break
            self._sleep(self.shutdown_poll)
            waited += self.shutdown_poll
        if channel.is_alive():
            logger.warning(
                "desktop backend %s did not stop within %.1fs; force-killing",
                self.spec.name,
                self.shutdown_grace,
            )
            channel.kill()
            forced = True
        logger.info("desktop backend %s shut down (forced=%s)", self.spec.name, forced)
        return forced
