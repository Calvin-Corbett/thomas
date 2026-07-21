"""Failure recovery and loop-breaking for agent runs (stdlib-only, deterministic).

CAP-005 -- "Failure recovery & loop-breaking".

When an attempt fails, a run must not simply retry the same thing forever. This
module provides :class:`RecoveryController`, which governs the response to a
failing attempt in three parts:

1. ALTERNATE STRATEGY
   On a failed attempt the controller selects a *different* strategy than any
   already tried. Tried strategies are tracked and never repeated;
   :meth:`RecoveryController.next_strategy` returns the next untried strategy or
   ``None`` when the injected strategy list is exhausted. A run therefore
   genuinely tries an alternate approach before giving up.

2. LOOP-BREAKING / CONTRADICTION-AWARE ESCALATION
   Each attempt has a *signature* ``(action, outcome)``. The controller watches
   the ordered attempt history for two failure shapes:

   * **contradiction** -- the actions *thrash*: an action recurs after a
     different action intervened (``A`` then ``B`` then ``A`` again -- "attempt
     A says X, attempt B undoes it, repeat"). This is an oscillation the run
     cannot escape by continuing.
   * **cycle** -- a full signature ``(action, outcome)`` repeats: the run has
     returned to a state it was already in.

   When either is detected, or when strategies are exhausted, the controller
   ESCALATES with a structured :class:`EscalationReason`
   (``CONTRADICTION`` / ``CYCLE_DETECTED`` / ``STRATEGIES_EXHAUSTED``) instead
   of looping forever. Contradiction is the more specific diagnosis and is
   reported in preference to a plain cycle.

3. FAILURE SUMMARY
   On escalation the controller produces a structured :class:`FailureSummary`:
   what was attempted (the goal), each strategy and its outcome, why the run is
   blocked, and the detected contradiction/cycle (the offending actions) if any.

The controller is deterministic and takes an injectable strategy list; it never
calls a live model. Callers run each strategy themselves and report the result
back as an :class:`Attempt` (in tests, via a fake executor).
"""

from __future__ import annotations

import dataclasses
import enum
from collections.abc import Callable, Sequence
from typing import Any


class AttemptOutcome(enum.Enum):
    """Outcome of a single strategy attempt."""

    SUCCESS = "success"
    FAILURE = "failure"


class EscalationReason(enum.Enum):
    """Why a run stopped recovering and escalated instead of looping."""

    CONTRADICTION = "contradiction"
    CYCLE_DETECTED = "cycle_detected"
    STRATEGIES_EXHAUSTED = "strategies_exhausted"


@dataclasses.dataclass(frozen=True)
class Strategy:
    """A named approach the run can attempt.

    ``name`` is the identity used for tried-tracking (never repeated). Two
    distinct strategies may still produce the same *action* at runtime -- that
    is exactly the situation loop-breaking exists to catch.
    """

    name: str
    description: str = ""

    @staticmethod
    def coerce(value: Strategy | str) -> Strategy:
        """Accept a bare string as shorthand for ``Strategy(name=value)``."""
        if isinstance(value, Strategy):
            return value
        return Strategy(name=str(value))


@dataclasses.dataclass(frozen=True)
class Attempt:
    """One executed strategy and what it did.

    ``action`` is the observable thing the attempt did (e.g. ``"set flag=on"``);
    it is what contradiction/cycle detection compares. ``outcome`` is whether
    the attempt succeeded. ``detail`` is free-form context for the summary.
    """

    strategy: str
    action: str
    outcome: AttemptOutcome
    detail: str = ""

    @property
    def signature(self) -> tuple[str, str]:
        """The ``(action, outcome)`` signature used for loop detection."""
        return (self.action, self.outcome.value)

    @property
    def succeeded(self) -> bool:
        return self.outcome is AttemptOutcome.SUCCESS


@dataclasses.dataclass(frozen=True)
class StrategyOutcome:
    """A strategy and its outcome, as recorded in a :class:`FailureSummary`."""

    strategy: str
    action: str
    outcome: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class FailureSummary:
    """Structured account of why a run is blocked, produced on escalation."""

    goal: str
    strategies_tried: tuple[StrategyOutcome, ...]
    reason: EscalationReason
    blocked_because: str
    contradiction: tuple[str, ...] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "strategies_tried": [s.as_dict() for s in self.strategies_tried],
            "reason": self.reason.value,
            "blocked_because": self.blocked_because,
            "contradiction": list(self.contradiction) if self.contradiction is not None else None,
        }


@dataclasses.dataclass(frozen=True)
class RecoveryResult:
    """Terminal result of driving a recovery: either success or escalation."""

    succeeded: bool
    escalated: bool
    attempts: tuple[Attempt, ...]
    winning_strategy: str | None = None
    reason: EscalationReason | None = None
    summary: FailureSummary | None = None


# A strategy selector maps (context, remaining ordered strategies, tried names)
# to the next strategy to try (or None). The default picks the first untried
# strategy in declaration order; a custom selector enables context-aware choice.
StrategySelector = Callable[[Any, Sequence[Strategy], frozenset], "Strategy | None"]

# An executor runs a chosen strategy against a context and reports the result.
StrategyExecutor = Callable[[Strategy, Any], Attempt]


def _default_selector(context: Any, strategies: Sequence[Strategy], tried: frozenset) -> Strategy | None:
    """Pick the first strategy whose name has not been tried, in order."""
    for strat in strategies:
        if strat.name not in tried:
            return strat
    return None


@dataclasses.dataclass(frozen=True)
class _Diagnosis:
    reason: EscalationReason
    detail: tuple[str, ...]


def _diagnose(attempts: Sequence[Attempt]) -> _Diagnosis | None:
    """Detect a contradiction (thrash) or a cycle (repeated signature).

    Contradiction is checked first because it is the more specific diagnosis: an
    action that recurs *after a different action intervened* is an oscillation
    (A -> B -> A). A plain repeated ``(action, outcome)`` signature with no
    intervening different action is a cycle.
    """
    actions = [a.action for a in attempts]
    first_seen: dict[str, int] = {}
    for i, act in enumerate(actions):
        if act in first_seen:
            prev = first_seen[act]
            if any(actions[k] != act for k in range(prev + 1, i)):
                return _Diagnosis(EscalationReason.CONTRADICTION, (actions[prev], actions[prev + 1], act))
        else:
            first_seen[act] = i

    seen_sigs: set[tuple[str, str]] = set()
    for attempt in attempts:
        sig = attempt.signature
        if sig in seen_sigs:
            return _Diagnosis(EscalationReason.CYCLE_DETECTED, (f"{sig[0]} -> {sig[1]}",))
        seen_sigs.add(sig)
    return None


class RecoveryController:
    """Governs how a run responds to failing attempts (see module docstring)."""

    def __init__(
        self,
        strategies: Sequence[Strategy | str],
        *,
        goal: str = "",
        selector: StrategySelector | None = None,
    ) -> None:
        self._strategies: tuple[Strategy, ...] = tuple(Strategy.coerce(s) for s in strategies)
        names = [s.name for s in self._strategies]
        if len(set(names)) != len(names):
            raise ValueError("strategy names must be unique")
        self._goal = goal
        self._selector: StrategySelector = selector or _default_selector
        self._attempts: list[Attempt] = []
        self._tried: list[str] = []

    # -- introspection -------------------------------------------------------

    @property
    def attempts(self) -> tuple[Attempt, ...]:
        return tuple(self._attempts)

    @property
    def tried(self) -> tuple[str, ...]:
        return tuple(self._tried)

    # -- alternate strategy selection ---------------------------------------

    def next_strategy(self, context: Any = None, tried: Sequence[str] | None = None) -> Strategy | None:
        """Return the next strategy that has not been tried, or ``None``.

        A strategy is never returned twice. ``tried`` may be passed explicitly;
        otherwise the controller's own tried set is used. The result is chosen
        by the injected ``selector`` (default: declaration order).
        """
        tried_set = frozenset(self._tried if tried is None else tried)
        return self._selector(context, self._strategies, tried_set)

    def record_attempt(self, attempt: Attempt) -> None:
        """Record an executed attempt, marking its strategy tried."""
        self._attempts.append(attempt)
        if attempt.strategy not in self._tried:
            self._tried.append(attempt.strategy)

    # -- escalation ----------------------------------------------------------

    def detect_escalation(self) -> EscalationReason | None:
        """Return a contradiction/cycle reason for the current history, if any."""
        diagnosis = _diagnose(self._attempts)
        return diagnosis.reason if diagnosis is not None else None

    def build_summary(self, reason: EscalationReason) -> FailureSummary:
        """Produce the structured failure summary for an escalation ``reason``."""
        diagnosis = _diagnose(self._attempts)
        contradiction = diagnosis.detail if diagnosis is not None else None
        outcomes = tuple(
            StrategyOutcome(
                strategy=a.strategy,
                action=a.action,
                outcome=a.outcome.value,
                detail=a.detail,
            )
            for a in self._attempts
        )
        return FailureSummary(
            goal=self._goal,
            strategies_tried=outcomes,
            reason=reason,
            blocked_because=self._blocked_because(reason, contradiction),
            contradiction=contradiction,
        )

    @staticmethod
    def _blocked_because(reason: EscalationReason, contradiction: tuple[str, ...] | None) -> str:
        if reason is EscalationReason.CONTRADICTION:
            path = " -> ".join(contradiction) if contradiction else "conflicting actions"
            return f"attempts contradict each other (thrashing between {path}); continuing cannot converge"
        if reason is EscalationReason.CYCLE_DETECTED:
            sig = contradiction[0] if contradiction else "a prior attempt"
            return f"attempts are cycling (repeated {sig}); the run returned to a state it was already in"
        return "every available strategy was tried and none succeeded"

    # -- driver --------------------------------------------------------------

    def run(self, executor: StrategyExecutor, context: Any = None) -> RecoveryResult:
        """Drive attempts until one succeeds or the run must escalate.

        For each step the controller selects an *alternate* (untried) strategy,
        the caller-provided ``executor`` runs it and reports an :class:`Attempt`,
        and the controller checks for a contradiction/cycle. If the attempt
        succeeds the run stops without escalating. If a contradiction/cycle is
        detected, or no untried strategy remains, the run escalates with a
        structured reason and a :class:`FailureSummary`.
        """
        while True:
            strat = self.next_strategy(context)
            if strat is None:
                return self._escalate(EscalationReason.STRATEGIES_EXHAUSTED)
            attempt = executor(strat, context)
            self.record_attempt(attempt)
            if attempt.succeeded:
                return RecoveryResult(
                    succeeded=True,
                    escalated=False,
                    attempts=self.attempts,
                    winning_strategy=strat.name,
                )
            reason = self.detect_escalation()
            if reason is not None:
                return self._escalate(reason)

    def _escalate(self, reason: EscalationReason) -> RecoveryResult:
        return RecoveryResult(
            succeeded=False,
            escalated=True,
            attempts=self.attempts,
            reason=reason,
            summary=self.build_summary(reason),
        )
