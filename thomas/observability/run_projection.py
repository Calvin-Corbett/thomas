"""Live run telemetry aggregation + completion projection (CAP-137).

This is the *core* the always-visible live-run widget reads. Feed it a stream
of run events -- turns starting and finishing, and tokens being consumed, each
carrying an **injected timestamp** -- and it maintains the live metrics the UI
needs to render at any moment:

* **cumulative turns** -- number of turns that have *finished*
* **cumulative tokens** -- total tokens consumed so far
* **rate** -- tokens/min and turns/min over a rolling time window
* **completion projection** -- estimated turns/tokens still remaining to a
  target, and an **ETA** to reach it, derived from the observed rate

Everything is deterministic: there is no wall-clock read and no RNG anywhere in
the math. Time comes exclusively from an injected ``clock`` callable and from
the timestamps carried on the events, so the same event stream evaluated at the
same clock value always yields an identical snapshot.

The rate is a genuine *rolling* rate. When :meth:`RunProjection.snapshot` is
taken at ``now = clock()``, only events whose timestamp lies in the half-open
window ``(now - window_seconds, now]`` count toward the rate. Each dimension
(tokens, turns) is divided by the span from its own oldest in-window event to
``now``. As older activity ages out of the window, the rate changes -- exactly
what a live "current pace" reading should do.

The completion projection turns the rate into remaining work + ETA toward an
injected target::

    remaining_tokens = max(target_tokens - cumulative_tokens, 0)
    eta_tokens_s     = remaining_tokens / tokens_per_second   (if rate > 0)

with the analogous computation for turns. When a target dimension still has
work left but its rate is zero or there is not enough data to measure a rate,
the ETA for that dimension -- and therefore the overall projection -- is
reported as **unknown** (``None``) rather than dividing by zero or fabricating a
number. The overall ETA is the *bottleneck*: the longer of the per-dimension
ETAs, because the run is only complete once every targeted dimension is met.

This module lives in the ``observability`` (infra) tier and imports only the
standard library.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import Enum

__all__ = [
    "EventKind",
    "RunEvent",
    "RunTarget",
    "RunSnapshot",
    "RunProjection",
]


class EventKind(str, Enum):
    """The kinds of run events the projection understands."""

    TURN_STARTED = "turn_started"
    TURN_FINISHED = "turn_finished"
    TOKENS = "tokens"


@dataclass(frozen=True)
class RunEvent:
    """A single telemetry event carrying an injected timestamp (seconds).

    ``tokens`` is only meaningful for :attr:`EventKind.TOKENS` events and is
    ignored otherwise.
    """

    kind: EventKind
    timestamp: float
    tokens: int = 0


@dataclass(frozen=True)
class RunTarget:
    """The completion target the projection estimates remaining work toward.

    Either dimension may be ``None`` to indicate "no target on this dimension",
    in which case that dimension does not constrain the overall ETA.
    """

    turns: int | None = None
    tokens: int | None = None


@dataclass(frozen=True)
class RunSnapshot:
    """An immutable, always-renderable view of the run at one clock instant."""

    now: float
    window_seconds: float

    # --- live cumulative metrics ---
    cumulative_turns: int
    cumulative_tokens: int
    turns_in_progress: int

    # --- rolling-window rate (None when there is not enough data) ---
    tokens_per_min: float | None
    turns_per_min: float | None

    # --- completion projection toward the target ---
    target_turns: int | None
    target_tokens: int | None
    remaining_turns: int | None
    remaining_tokens: int | None
    eta_seconds_turns: float | None
    eta_seconds_tokens: float | None
    eta_seconds: float | None
    projection_known: bool

    def as_dict(self) -> dict[str, object]:
        """Flat, JSON-friendly mapping for a route/UI layer to serialize."""
        return {
            "now": self.now,
            "window_seconds": self.window_seconds,
            "cumulative_turns": self.cumulative_turns,
            "cumulative_tokens": self.cumulative_tokens,
            "turns_in_progress": self.turns_in_progress,
            "tokens_per_min": self.tokens_per_min,
            "turns_per_min": self.turns_per_min,
            "target_turns": self.target_turns,
            "target_tokens": self.target_tokens,
            "remaining_turns": self.remaining_turns,
            "remaining_tokens": self.remaining_tokens,
            "eta_seconds_turns": self.eta_seconds_turns,
            "eta_seconds_tokens": self.eta_seconds_tokens,
            "eta_seconds": self.eta_seconds,
            "projection_known": self.projection_known,
        }


def _monotonic_now() -> float:
    """Default clock. Injected out in tests for determinism."""
    return time.monotonic()


@dataclass
class RunProjection:
    """Live telemetry aggregator + completion projector.

    Parameters
    ----------
    window_seconds:
        Width of the rolling window used for the rate, in seconds.
    clock:
        Injected ``() -> float`` returning "now" in seconds. Defaults to
        :func:`time.monotonic`; tests inject a controllable clock.
    target:
        The completion target the projection estimates toward. May be updated
        later via :meth:`set_target`.
    """

    window_seconds: float = 60.0
    clock: Callable[[], float] = _monotonic_now
    target: RunTarget = field(default_factory=RunTarget)

    _events: list[RunEvent] = field(default_factory=list, init=False, repr=False)
    _cumulative_turns: int = field(default=0, init=False)
    _cumulative_tokens: int = field(default=0, init=False)
    _turns_started: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if self.window_seconds <= 0:
            raise ValueError("window_seconds must be positive")

    # ------------------------------------------------------------------ #
    # Ingestion
    # ------------------------------------------------------------------ #
    def ingest(self, event: RunEvent) -> None:
        """Record a single event into the running aggregate."""
        self._events.append(event)
        if event.kind is EventKind.TURN_STARTED:
            self._turns_started += 1
        elif event.kind is EventKind.TURN_FINISHED:
            self._cumulative_turns += 1
        elif event.kind is EventKind.TOKENS:
            self._cumulative_tokens += int(event.tokens)

    def ingest_many(self, events: Iterable[RunEvent]) -> None:
        """Record a batch of events in order."""
        for event in events:
            self.ingest(event)

    def turn_started(self, timestamp: float) -> None:
        """Convenience: record a turn-start event at ``timestamp``."""
        self.ingest(RunEvent(EventKind.TURN_STARTED, timestamp))

    def turn_finished(self, timestamp: float) -> None:
        """Convenience: record a turn-finish event at ``timestamp``."""
        self.ingest(RunEvent(EventKind.TURN_FINISHED, timestamp))

    def record_tokens(self, tokens: int, timestamp: float) -> None:
        """Convenience: record ``tokens`` consumed at ``timestamp``."""
        self.ingest(RunEvent(EventKind.TOKENS, timestamp, tokens=int(tokens)))

    def set_target(self, target: RunTarget) -> None:
        """Update the completion target the projection estimates toward."""
        self.target = target

    # ------------------------------------------------------------------ #
    # Rate computation (rolling window, per dimension)
    # ------------------------------------------------------------------ #
    def _rate_per_second(
        self,
        now: float,
        kind: EventKind,
        value_of: Callable[[RunEvent], float],
    ) -> float | None:
        """Rolling per-second rate for one dimension, or ``None`` if unknown.

        Considers only events of ``kind`` whose timestamp is in the half-open
        window ``(now - window_seconds, now]`` and divides their summed value by
        the span from the oldest such event to ``now``. Returns ``None`` when
        there is no in-window activity or the span is non-positive (which would
        otherwise be a divide-by-zero).
        """
        window_start = now - self.window_seconds
        total = 0.0
        oldest: float | None = None
        for event in self._events:
            if event.kind is not kind:
                continue
            ts = event.timestamp
            if ts <= window_start or ts > now:
                continue
            total += value_of(event)
            if oldest is None or ts < oldest:
                oldest = ts
        if oldest is None:
            return None
        span = now - oldest
        if span <= 0:
            return None
        return total / span

    # ------------------------------------------------------------------ #
    # Snapshot / projection
    # ------------------------------------------------------------------ #
    def snapshot(self, now: float | None = None) -> RunSnapshot:
        """Compute an always-renderable snapshot at ``now`` (default: clock())."""
        if now is None:
            now = self.clock()

        tokens_per_second = self._rate_per_second(now, EventKind.TOKENS, lambda e: float(e.tokens))
        turns_per_second = self._rate_per_second(now, EventKind.TURN_FINISHED, lambda _e: 1.0)

        tokens_per_min = None if tokens_per_second is None else tokens_per_second * 60.0
        turns_per_min = None if turns_per_second is None else turns_per_second * 60.0

        remaining_turns = _remaining(self.target.turns, self._cumulative_turns)
        remaining_tokens = _remaining(self.target.tokens, self._cumulative_tokens)

        eta_turns, turns_known = _eta_for_dimension(remaining_turns, turns_per_second)
        eta_tokens, tokens_known = _eta_for_dimension(remaining_tokens, tokens_per_second)

        # Overall ETA is the bottleneck: the run finishes only once every
        # targeted dimension is met, so take the longer of the known ETAs.
        overall, projection_known = _combine_eta((turns_known, eta_turns), (tokens_known, eta_tokens))

        return RunSnapshot(
            now=now,
            window_seconds=self.window_seconds,
            cumulative_turns=self._cumulative_turns,
            cumulative_tokens=self._cumulative_tokens,
            turns_in_progress=max(self._turns_started - self._cumulative_turns, 0),
            tokens_per_min=tokens_per_min,
            turns_per_min=turns_per_min,
            target_turns=self.target.turns,
            target_tokens=self.target.tokens,
            remaining_turns=remaining_turns,
            remaining_tokens=remaining_tokens,
            eta_seconds_turns=eta_turns,
            eta_seconds_tokens=eta_tokens,
            eta_seconds=overall,
            projection_known=projection_known,
        )


def _remaining(target: int | None, done: int) -> int | None:
    """Remaining work toward ``target`` (never negative), or ``None`` if no target."""
    if target is None:
        return None
    return max(target - done, 0)


def _eta_for_dimension(remaining: int | None, rate_per_second: float | None) -> tuple[float | None, bool]:
    """ETA for one dimension.

    Returns ``(eta_seconds, known)``:

    * no target on this dimension -> ``(None, True)`` (does not constrain).
    * already complete (remaining == 0) -> ``(0.0, True)``.
    * remaining > 0 with a positive rate -> ``(remaining / rate, True)``.
    * remaining > 0 but rate unknown or non-positive -> ``(None, False)``.
    """
    if remaining is None:
        return None, True
    if remaining <= 0:
        return 0.0, True
    if rate_per_second is None or rate_per_second <= 0:
        return None, False
    return remaining / rate_per_second, True


def _combine_eta(
    turns: tuple[bool, float | None],
    tokens: tuple[bool, float | None],
) -> tuple[float | None, bool]:
    """Combine per-dimension ETAs into an overall (bottleneck) ETA.

    If any dimension that still has work is unknown, the overall projection is
    unknown. Otherwise the overall ETA is the max of the concrete per-dimension
    ETAs (both dimensions must complete). With no targets at all the projection
    is trivially known with a ``None`` ETA (nothing to reach).
    """
    turns_known, eta_turns = turns
    tokens_known, eta_tokens = tokens
    if not (turns_known and tokens_known):
        return None, False
    concrete = [e for e in (eta_turns, eta_tokens) if e is not None]
    if not concrete:
        return None, True
    return max(concrete), True
