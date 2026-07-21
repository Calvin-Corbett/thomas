"""Configurable mid-run check-in policies with a resumable acknowledgement gate.

CAP-051: long-running agent runs can be configured to check in with the user
on a cadence expressed as any combination of:

- a time interval (seconds since the last check-in),
- a step interval (every N tool steps), and
- a token budget (every N tokens consumed).

Each threshold independently triggers a check-in when crossed. A check-in
carries a payload describing what the run has done since the last check-in
plus run totals. When ``ack_required`` is set, the run pauses at the check-in
behind an :class:`AcknowledgementGate` until ``acknowledge()`` is called. The
gate and policy counters serialize via ``to_state``/``from_state`` so a paused
run survives a restart and resumes exactly once acknowledged.

Safe default: when nothing is configured, :func:`resolve_checkin_policy`
returns ``None`` and the agent loop skips all check-in work entirely.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

_STATE_VERSION = 1
_MAX_ACTIVITY_LABELS = 25


def _coerce_positive_float(value: Any) -> float | None:
    """Return ``value`` as a positive float, or ``None`` when unset/invalid."""
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _coerce_positive_int(value: Any) -> int | None:
    """Return ``value`` as a positive int, or ``None`` when unset/invalid."""
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


@dataclass(frozen=True)
class CheckinConfig:
    """Cadence thresholds for mid-run check-ins.

    Any threshold left as ``None`` (or non-positive) is disabled. With every
    threshold disabled the policy never triggers.
    """

    interval_seconds: float | None = None
    step_interval: int | None = None
    token_interval: int | None = None
    ack_required: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "interval_seconds", _coerce_positive_float(self.interval_seconds))
        object.__setattr__(self, "step_interval", _coerce_positive_int(self.step_interval))
        object.__setattr__(self, "token_interval", _coerce_positive_int(self.token_interval))
        object.__setattr__(self, "ack_required", bool(self.ack_required))

    @property
    def enabled(self) -> bool:
        """True when at least one threshold is configured."""
        return any(v is not None for v in (self.interval_seconds, self.step_interval, self.token_interval))

    def to_dict(self) -> dict[str, Any]:
        return {
            "interval_seconds": self.interval_seconds,
            "step_interval": self.step_interval,
            "token_interval": self.token_interval,
            "ack_required": self.ack_required,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CheckinConfig:
        return cls(
            interval_seconds=data.get("interval_seconds"),
            step_interval=data.get("step_interval"),
            token_interval=data.get("token_interval"),
            ack_required=bool(data.get("ack_required", False)),
        )


@dataclass(frozen=True)
class CheckinEvent:
    """Payload for one fired check-in.

    Describes activity since the previous check-in (steps, tokens, elapsed
    seconds, tool labels), which thresholds crossed, and run totals so far.
    """

    checkin_id: str
    sequence: int
    thresholds_crossed: tuple[str, ...]
    steps_since_last: int
    tokens_since_last: int
    seconds_since_last: float
    activity_since_last: tuple[str, ...]
    total_steps: int
    total_tokens: int
    total_seconds: float
    ack_required: bool

    @property
    def message(self) -> str:
        """One-line human summary suitable for a status event."""
        crossed = ", ".join(self.thresholds_crossed) or "none"
        summary = (
            f"Check-in #{self.sequence}: {self.steps_since_last} tool step(s), "
            f"~{self.tokens_since_last:,} tokens, {self.seconds_since_last:.0f}s since last check-in "
            f"(thresholds crossed: {crossed}; run totals: {self.total_steps} step(s), "
            f"~{self.total_tokens:,} tokens)."
        )
        if self.ack_required:
            summary += " Paused — acknowledge to continue."
        return summary

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkin_id": self.checkin_id,
            "sequence": self.sequence,
            "thresholds_crossed": list(self.thresholds_crossed),
            "steps_since_last": self.steps_since_last,
            "tokens_since_last": self.tokens_since_last,
            "seconds_since_last": self.seconds_since_last,
            "activity_since_last": list(self.activity_since_last),
            "total_steps": self.total_steps,
            "total_tokens": self.total_tokens,
            "total_seconds": self.total_seconds,
            "ack_required": self.ack_required,
        }


class AcknowledgementGate:
    """Await-able / pollable gate a paused run waits on until acknowledged.

    The gate starts open. ``require_ack(checkin_id)`` closes it; ``wait()``
    then blocks until ``acknowledge()`` re-opens it. ``is_waiting()`` allows
    polling. ``to_state``/``from_state`` persist the closed/open state so a
    paused run survives restart and resumes exactly once acknowledged.
    """

    def __init__(self) -> None:
        self._ready = asyncio.Event()
        self._ready.set()
        self._waiting_for: str | None = None

    @property
    def waiting_for(self) -> str | None:
        """The check-in id currently blocking the run, if any."""
        return self._waiting_for

    def require_ack(self, checkin_id: str) -> None:
        """Close the gate until ``acknowledge`` is called for this check-in."""
        self._waiting_for = str(checkin_id)
        self._ready.clear()

    def is_waiting(self) -> bool:
        """True while the run is paused waiting for an acknowledgement."""
        return self._waiting_for is not None

    def acknowledge(self, checkin_id: str | None = None) -> bool:
        """Open the gate. Returns True when a paused run was released.

        When ``checkin_id`` is given it must match the pending check-in;
        acknowledging an already-open gate is a no-op returning False.
        """
        if self._waiting_for is None:
            return False
        if checkin_id is not None and str(checkin_id) != self._waiting_for:
            return False
        self._waiting_for = None
        self._ready.set()
        return True

    async def wait(self) -> None:
        """Block until the gate is open. Returns immediately when open."""
        await self._ready.wait()

    def to_state(self) -> dict[str, Any]:
        return {"waiting_for": self._waiting_for}

    @classmethod
    def from_state(cls, state: Mapping[str, Any]) -> AcknowledgementGate:
        gate = cls()
        waiting_for = state.get("waiting_for")
        if waiting_for:
            gate.require_ack(str(waiting_for))
        return gate


class CheckinPolicy:
    """Tracks run progress and fires :class:`CheckinEvent`s on threshold cross.

    Thread-of-control contract: the agent loop calls ``record_step`` /
    ``record_tokens`` (or the combined ``observe_step``) at each tool-step
    boundary; each call returns a fired event or ``None``. Time thresholds are
    evaluated at the same boundaries, so a time check-in fires on the first
    boundary after the interval elapses.
    """

    def __init__(
        self,
        config: CheckinConfig,
        *,
        clock: Callable[[], float] = time.monotonic,
        gate: AcknowledgementGate | None = None,
    ) -> None:
        self._config = config
        self._clock = clock
        self.gate = gate if gate is not None else AcknowledgementGate()
        now = clock()
        self._started_at = now
        self._window_started_at = now
        self._sequence = 0
        self._total_steps = 0
        self._total_tokens = 0
        self._steps_since = 0
        self._tokens_since = 0
        self._last_absolute_tokens = 0
        self._activity: list[str] = []

    @property
    def config(self) -> CheckinConfig:
        return self._config

    @property
    def total_steps(self) -> int:
        return self._total_steps

    @property
    def total_tokens(self) -> int:
        return self._total_tokens

    # ── recording ────────────────────────────────────────────────────

    def record_step(self, *, label: str = "") -> CheckinEvent | None:
        """Record one completed tool step; fire when a threshold crossed."""
        if not self._config.enabled:
            return None
        self._total_steps += 1
        self._steps_since += 1
        if label and len(self._activity) < _MAX_ACTIVITY_LABELS:
            self._activity.append(str(label))
        return self._maybe_fire()

    def record_tokens(self, tokens: int, *, absolute: bool = False) -> CheckinEvent | None:
        """Record token consumption; fire when a threshold crossed.

        With ``absolute=True`` the value is the run's cumulative total and the
        policy derives the delta itself (robust against duplicate reports).
        """
        if not self._config.enabled:
            return None
        try:
            amount = int(tokens)
        except (TypeError, ValueError):
            amount = 0
        if absolute:
            total = max(0, amount)
            delta = max(0, total - self._last_absolute_tokens)
            self._last_absolute_tokens = total
        else:
            delta = max(0, amount)
            self._last_absolute_tokens += delta
        self._total_tokens += delta
        self._tokens_since += delta
        return self._maybe_fire()

    def check_time(self) -> CheckinEvent | None:
        """Evaluate only the elapsed-time threshold (for idle boundaries)."""
        if not self._config.enabled:
            return None
        return self._maybe_fire()

    def observe_step(self, *, total_tokens: int | None = None, label: str = "") -> list[CheckinEvent]:
        """One tool-step boundary: record tokens then the step.

        Returns every check-in fired at this boundary (usually zero or one;
        two when the token threshold and a step threshold cross back-to-back).
        """
        if not self._config.enabled:
            return []
        fired: list[CheckinEvent] = []
        if total_tokens is not None:
            event = self.record_tokens(total_tokens, absolute=True)
            if event is not None:
                fired.append(event)
        event = self.record_step(label=label)
        if event is not None:
            fired.append(event)
        return fired

    # ── acknowledgement ──────────────────────────────────────────────

    def is_waiting(self) -> bool:
        """True while paused at an unacknowledged check-in."""
        return self.gate.is_waiting()

    def acknowledge(self, checkin_id: str | None = None) -> bool:
        """Acknowledge the pending check-in, releasing a paused run."""
        return self.gate.acknowledge(checkin_id)

    async def wait_until_acknowledged(self) -> None:
        """Await the gate; returns immediately when no ack is pending."""
        await self.gate.wait()

    # ── persistence ──────────────────────────────────────────────────

    def to_state(self) -> dict[str, Any]:
        """Serializable snapshot; restore with :meth:`from_state`."""
        now = self._clock()
        return {
            "version": _STATE_VERSION,
            "config": self._config.to_dict(),
            "sequence": self._sequence,
            "total_steps": self._total_steps,
            "total_tokens": self._total_tokens,
            "steps_since_last": self._steps_since,
            "tokens_since_last": self._tokens_since,
            "seconds_since_window_start": max(0.0, now - self._window_started_at),
            "total_seconds": max(0.0, now - self._started_at),
            "last_absolute_tokens": self._last_absolute_tokens,
            "activity_since_last": list(self._activity),
            "gate": self.gate.to_state(),
        }

    @classmethod
    def from_state(
        cls,
        state: Mapping[str, Any],
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> CheckinPolicy:
        """Rebuild a policy (including a pending pause) from ``to_state``."""
        config_data = state.get("config")
        config = CheckinConfig.from_dict(config_data if isinstance(config_data, Mapping) else {})
        gate_data = state.get("gate")
        gate = AcknowledgementGate.from_state(gate_data if isinstance(gate_data, Mapping) else {})
        policy = cls(config, clock=clock, gate=gate)
        now = clock()
        policy._sequence = max(0, _coerce_positive_int(state.get("sequence")) or 0)
        policy._total_steps = max(0, _coerce_positive_int(state.get("total_steps")) or 0)
        policy._total_tokens = max(0, _coerce_positive_int(state.get("total_tokens")) or 0)
        policy._steps_since = max(0, _coerce_positive_int(state.get("steps_since_last")) or 0)
        policy._tokens_since = max(0, _coerce_positive_int(state.get("tokens_since_last")) or 0)
        policy._last_absolute_tokens = max(0, _coerce_positive_int(state.get("last_absolute_tokens")) or 0)
        window_elapsed = _coerce_positive_float(state.get("seconds_since_window_start")) or 0.0
        run_elapsed = _coerce_positive_float(state.get("total_seconds")) or 0.0
        policy._window_started_at = now - window_elapsed
        policy._started_at = now - run_elapsed
        activity = state.get("activity_since_last")
        if isinstance(activity, list):
            policy._activity = [str(a) for a in activity[:_MAX_ACTIVITY_LABELS]]
        return policy

    # ── internals ────────────────────────────────────────────────────

    def _crossed_thresholds(self, now: float) -> tuple[str, ...]:
        crossed: list[str] = []
        cfg = self._config
        if cfg.interval_seconds is not None and (now - self._window_started_at) >= cfg.interval_seconds:
            crossed.append("time")
        if cfg.step_interval is not None and self._steps_since >= cfg.step_interval:
            crossed.append("steps")
        if cfg.token_interval is not None and self._tokens_since >= cfg.token_interval:
            crossed.append("tokens")
        return tuple(crossed)

    def _maybe_fire(self) -> CheckinEvent | None:
        if self.gate.is_waiting():
            # Already paused at an unacknowledged check-in; never stack a second.
            return None
        now = self._clock()
        crossed = self._crossed_thresholds(now)
        if not crossed:
            return None
        self._sequence += 1
        event = CheckinEvent(
            checkin_id=uuid.uuid4().hex,
            sequence=self._sequence,
            thresholds_crossed=crossed,
            steps_since_last=self._steps_since,
            tokens_since_last=self._tokens_since,
            seconds_since_last=max(0.0, now - self._window_started_at),
            activity_since_last=tuple(self._activity),
            total_steps=self._total_steps,
            total_tokens=self._total_tokens,
            total_seconds=max(0.0, now - self._started_at),
            ack_required=self._config.ack_required,
        )
        self._steps_since = 0
        self._tokens_since = 0
        self._activity = []
        self._window_started_at = now
        if self._config.ack_required:
            self.gate.require_ack(event.checkin_id)
        log.info("Mid-run check-in fired: %s", event.message)
        return event


def checkin_config_from(source: Any) -> CheckinConfig | None:
    """Extract a :class:`CheckinConfig` from an app config object or mapping.

    Looks for a ``checkin`` section (attribute or key) carrying any of
    ``interval_seconds`` / ``step_interval`` / ``token_interval`` and an
    optional ``ack_required`` flag. Returns ``None`` when nothing is
    configured — the zero-overhead default.
    """
    if source is None:
        return None
    section = source.get("checkin") if isinstance(source, Mapping) else getattr(source, "checkin", None)
    if section is None:
        return None

    def _field(name: str, default: Any = None) -> Any:
        if isinstance(section, Mapping):
            return section.get(name, default)
        return getattr(section, name, default)

    config = CheckinConfig(
        interval_seconds=_field("interval_seconds"),
        step_interval=_field("step_interval"),
        token_interval=_field("token_interval"),
        ack_required=bool(_field("ack_required", False)),
    )
    return config if config.enabled else None


def resolve_checkin_policy(
    config: Any,
    *,
    clock: Callable[[], float] = time.monotonic,
) -> CheckinPolicy | None:
    """Build a :class:`CheckinPolicy` from app config, or ``None`` when unset."""
    checkin_config = checkin_config_from(config)
    if checkin_config is None:
        return None
    return CheckinPolicy(checkin_config, clock=clock)
