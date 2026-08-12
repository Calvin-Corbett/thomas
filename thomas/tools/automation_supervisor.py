"""CAP-077 L2: always-on host supervisor for persistent automations.

An :class:`AutomationSupervisor` keeps long-lived, "always-on" automations
alive across failures. It provides the three capabilities the frontier rubric
requires of a persistent-automation host:

1. **Restart SLA.** When a supervised automation is observed down, the
   supervisor restarts it and records the restart *latency* (time from the
   moment the outage was observed to the moment the restart completed). If a
   restart takes longer than the automation's configured SLA window it is
   flagged as an :class:`RestartRecord` with ``sla_breach = True``.

2. **Missed-work report.** Each automation may carry a schedule of work it is
   supposed to run. While the automation is down that scheduled work does not
   run, so on recovery the supervisor emits a structured
   :class:`MissedWorkReport` enumerating exactly which scheduled items fell
   inside the downtime window.

3. **Accumulating role memory.** Every automation owns a durable *role memory*
   that survives restarts -- restarting an automation never wipes its memory;
   new facts append. Each restart also appends a fact automatically, so the
   memory literally accumulates the automation's operating history. The store
   is persisted as JSON (path overridable via the
   ``THOMAS_AUTOMATION_MEMORY_FILE`` environment variable or a constructor
   argument), so it also survives a restart of the supervisor process itself.

Determinism / hermeticity: the supervisor takes an **injected clock** (any
zero-arg callable returning a float "seconds" value) and per-automation
**injected health-probe / restart callables**. No real processes, wall-clock
sleeps, or network are used, so behaviour is fully reproducible in tests.

This module depends only on the standard library (tools-tier rule: no imports
from ``agent``/``server``/``cli``).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

ClockFn = Callable[[], float]
ProbeFn = Callable[[], bool]
RestartFn = Callable[[], None]

MEMORY_PATH_ENV = "THOMAS_AUTOMATION_MEMORY_FILE"


@dataclass(frozen=True)
class ScheduledWork:
    """One unit of scheduled work an automation is meant to run at ``run_at``."""

    automation: str
    run_at: float
    label: str


@dataclass(frozen=True)
class RestartRecord:
    """Evidence for one restart the supervisor performed.

    Attributes:
        automation: Name of the automation that was restarted.
        observed_down_at: Clock value when the outage was observed.
        restarted_at: Clock value when the restart completed.
        latency_seconds: ``restarted_at - observed_down_at`` (the restart SLA
            is measured against this).
        sla_seconds: The SLA window this restart was judged against.
        sla_breach: ``True`` if ``latency_seconds`` exceeded ``sla_seconds``.
        restart_index: 1-based count of restarts for this automation.
    """

    automation: str
    observed_down_at: float
    restarted_at: float
    latency_seconds: float
    sla_seconds: float
    sla_breach: bool
    restart_index: int


@dataclass(frozen=True)
class MissedWorkReport:
    """Scheduled work an automation missed during a single downtime window.

    Attributes:
        automation: Name of the automation.
        down_since: Best estimate of when the automation went down (the last
            time it was confirmed healthy, or the moment the outage was first
            observed if it was never seen healthy).
        recovered_at: Clock value when the automation was restored.
        missed: The scheduled items whose ``run_at`` fell inside the downtime
            window, in schedule order.
    """

    automation: str
    down_since: float
    recovered_at: float
    missed: tuple[ScheduledWork, ...]

    @property
    def missed_count(self) -> int:
        return len(self.missed)


@dataclass(frozen=True)
class RoleMemoryFact:
    """One durable fact in an automation's accumulating role memory."""

    text: str
    at: float
    source: str


@dataclass
class TickResult:
    """Outcome of a single :meth:`AutomationSupervisor.tick`.

    ``restart`` and ``missed_report`` are populated only when the tick observed
    the automation down and performed a recovery.
    """

    automation: str
    healthy: bool
    restart: RestartRecord | None = None
    missed_report: MissedWorkReport | None = None


@dataclass
class _Registration:
    name: str
    sla_seconds: float
    health_probe: ProbeFn
    restart_action: RestartFn
    schedule: list[ScheduledWork] = field(default_factory=list)


@dataclass
class _State:
    last_healthy: float | None = None
    restart_count: int = 0
    consumed: set[int] = field(default_factory=set)


def _default_memory_path() -> Path:
    env = os.environ.get(MEMORY_PATH_ENV, "").strip()
    if env:
        return Path(env)
    return Path(tempfile.gettempdir()) / "thomas_automation" / "role_memory.json"


class AutomationSupervisor:
    """Keeps persistent automations alive with restart SLA, missed-work
    reports, and durable accumulating role memory.

    Args:
        clock: Zero-arg callable returning the current time in seconds. All
            timing (restart latency, downtime windows) is measured with this,
            so tests can inject a controllable fake clock.
        memory_path: Where the role-memory JSON store lives. Defaults to the
            ``THOMAS_AUTOMATION_MEMORY_FILE`` environment variable, else a file
            under the system temp directory.
    """

    def __init__(
        self,
        *,
        clock: ClockFn,
        memory_path: str | os.PathLike[str] | None = None,
    ) -> None:
        self._clock = clock
        self._memory_path = Path(memory_path) if memory_path is not None else _default_memory_path()
        self._registrations: dict[str, _Registration] = {}
        self._states: dict[str, _State] = {}
        self._restarts: list[RestartRecord] = []
        self._lock = threading.RLock()
        self._memory: dict[str, list[RoleMemoryFact]] = self._load_memory()

    # -- registration ------------------------------------------------------

    def register(
        self,
        name: str,
        *,
        sla_seconds: float,
        health_probe: ProbeFn,
        restart_action: RestartFn,
        schedule: list[ScheduledWork] | None = None,
    ) -> None:
        """Register a persistent automation under supervision.

        Args:
            name: Unique automation name.
            sla_seconds: Restart SLA window; a restart slower than this is
                flagged as a breach.
            health_probe: Zero-arg callable returning ``True`` when the
                automation is healthy/up, ``False`` when it is down.
            restart_action: Zero-arg callable that performs the restart. It may
                advance the injected clock to model restart latency.
            schedule: Optional scheduled work the automation is meant to run.

        Raises:
            ValueError: If ``name`` is already registered or ``sla_seconds`` is
                not positive.
        """
        if sla_seconds <= 0:
            raise ValueError("sla_seconds must be positive")
        with self._lock:
            if name in self._registrations:
                raise ValueError(f"automation {name!r} already registered")
            self._registrations[name] = _Registration(
                name=name,
                sla_seconds=float(sla_seconds),
                health_probe=health_probe,
                restart_action=restart_action,
                schedule=list(schedule or []),
            )
            self._states[name] = _State()
            self._memory.setdefault(name, [])

    def schedule_work(self, name: str, run_at: float, label: str) -> ScheduledWork:
        """Append one scheduled work item to a registered automation."""
        with self._lock:
            reg = self._require(name)
            work = ScheduledWork(automation=name, run_at=float(run_at), label=label)
            reg.schedule.append(work)
            return work

    # -- supervision -------------------------------------------------------

    def tick(self, name: str) -> TickResult:
        """Probe one automation once and, if it is down, restart it.

        On a down observation this: performs the restart, records a
        :class:`RestartRecord` (with latency and SLA-breach flag), appends a
        restart fact to the automation's role memory, and returns a
        :class:`MissedWorkReport` covering the downtime window.

        Returns:
            A :class:`TickResult`. When the automation was healthy, ``restart``
            and ``missed_report`` are ``None``.
        """
        with self._lock:
            reg = self._require(name)
            state = self._states[name]
            now = self._clock()

            if reg.health_probe():
                state.last_healthy = now
                return TickResult(automation=name, healthy=True)

            down_since = state.last_healthy if state.last_healthy is not None else now
            observed_down_at = now

            reg.restart_action()

            restarted_at = self._clock()
            latency = restarted_at - observed_down_at
            state.restart_count += 1
            record = RestartRecord(
                automation=name,
                observed_down_at=observed_down_at,
                restarted_at=restarted_at,
                latency_seconds=latency,
                sla_seconds=reg.sla_seconds,
                sla_breach=latency > reg.sla_seconds,
                restart_index=state.restart_count,
            )
            self._restarts.append(record)

            self._append_memory(
                name,
                text=(
                    f"restart #{record.restart_index}: latency={latency:.3f}s "
                    f"sla={reg.sla_seconds:.3f}s breach={record.sla_breach}"
                ),
                at=restarted_at,
                source="restart",
            )

            report = self._build_missed_report(reg, state, down_since, restarted_at)
            state.last_healthy = restarted_at
            return TickResult(
                automation=name,
                healthy=False,
                restart=record,
                missed_report=report,
            )

    def _build_missed_report(
        self,
        reg: _Registration,
        state: _State,
        down_since: float,
        recovered_at: float,
    ) -> MissedWorkReport:
        missed: list[ScheduledWork] = []
        for idx, work in enumerate(reg.schedule):
            if idx in state.consumed:
                continue
            if down_since < work.run_at <= recovered_at:
                state.consumed.add(idx)
                missed.append(work)
        return MissedWorkReport(
            automation=reg.name,
            down_since=down_since,
            recovered_at=recovered_at,
            missed=tuple(missed),
        )

    # -- restart history ---------------------------------------------------

    def restart_history(self, name: str | None = None) -> list[RestartRecord]:
        """All restart records, optionally filtered to a single automation."""
        with self._lock:
            if name is None:
                return list(self._restarts)
            return [r for r in self._restarts if r.automation == name]

    def sla_breaches(self, name: str | None = None) -> list[RestartRecord]:
        """Restart records that breached their SLA window."""
        return [r for r in self.restart_history(name) if r.sla_breach]

    # -- role memory -------------------------------------------------------

    def remember(self, name: str, text: str, *, source: str = "manual") -> RoleMemoryFact:
        """Append a fact to an automation's durable role memory."""
        with self._lock:
            self._require(name)
            return self._append_memory(name, text=text, at=self._clock(), source=source)

    def role_memory(self, name: str) -> list[RoleMemoryFact]:
        """Return the accumulated role-memory facts for an automation."""
        with self._lock:
            return list(self._memory.get(name, []))

    def _append_memory(self, name: str, *, text: str, at: float, source: str) -> RoleMemoryFact:
        fact = RoleMemoryFact(text=text, at=at, source=source)
        self._memory.setdefault(name, []).append(fact)
        self._save_memory()
        return fact

    # -- persistence -------------------------------------------------------

    def _load_memory(self) -> dict[str, list[RoleMemoryFact]]:
        if not self._memory_path.exists():
            return {}
        try:
            raw = json.loads(self._memory_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("could not load role memory from %s (%s); starting empty", self._memory_path, e)
            return {}
        memory: dict[str, list[RoleMemoryFact]] = {}
        for name, facts in raw.items():
            memory[name] = [
                RoleMemoryFact(
                    text=str(f.get("text", "")),
                    at=float(f.get("at", 0.0)),
                    source=str(f.get("source", "unknown")),
                )
                for f in facts
            ]
        return memory

    def _save_memory(self) -> None:
        payload = {name: [asdict(f) for f in facts] for name, facts in self._memory.items()}
        try:
            self._memory_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._memory_path.with_suffix(self._memory_path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
            os.replace(tmp, self._memory_path)
        except OSError as e:
            logger.warning("could not persist role memory to %s (%s)", self._memory_path, e)

    # -- internals ---------------------------------------------------------

    def _require(self, name: str) -> _Registration:
        reg = self._registrations.get(name)
        if reg is None:
            raise KeyError(f"automation {name!r} is not registered")
        return reg
