"""Benchmarked, per-task FAST inference tier with latency + edit-quality gates.

Some tasks are cheap enough that a smaller/faster model tier answers them well;
others need the standard tier. This module offers a :class:`FastTierRouter` that
decides *per task* whether to use the FAST tier, guarded by two independent
quality bars:

1. **Latency gate** -- the fast tier is only used for a task whose *expected*
   latency fits inside a configured budget. A task that breaches the budget is
   never fast-tiered; it goes straight to the standard tier. Every task that
   does run records its *measured* latency (via an injected clock).

2. **Edit-quality gate** -- the fast tier's output is scored by an injected
   quality scorer (e.g. edit-correctness / diff-applies-cleanly). If the score
   falls below the configured gate the router **falls back** to the standard
   tier and records the fallback.

Everything is deterministic and hermetic: the clock and the quality scorer are
injected, the tier runners are injected callables, and nothing here touches a
live model, the network, or wall-clock time.

Design note on the two senses of "latency" the acceptance line names
("measured/expected latency"): the gate that *decides whether to try the fast
tier* is predictive -- it reads a task's ``expected_latency_s``. The latency the
router *records* for a task is the real elapsed time measured around execution
with the injected clock. The quality gate is what can trigger a fallback after
the fast tier has actually run.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

# A clock is any zero-arg callable returning a monotonically-nondecreasing float
# (seconds). Real usage injects ``time.monotonic``; tests inject a ManualClock.
Clock = Callable[[], float]

# A tier runner takes a task and returns the tier's raw output text. It is also
# what advances the injected clock in a hermetic test (modelling elapsed time).
TierRunner = Callable[["Task"], str]

# A quality scorer grades a tier's output for a task, in [0.0, 1.0].
QualityScorer = Callable[["Task", str], float]

FAST = "fast"
STANDARD = "standard"

# Route reasons.
REASON_FAST_ACCEPTED = "fast_accepted"
REASON_LATENCY_GATE = "latency_gate"
REASON_QUALITY_GATE = "quality_gate"


@dataclass(frozen=True)
class Task:
    """A unit of work the router may send to the fast or standard tier.

    ``expected_latency_s`` is the *predicted* cost used by the latency gate to
    decide whether the fast tier is eligible. ``payload`` is opaque to the
    router and is only handed to the injected runners / scorer.
    """

    task_id: str
    payload: Any = None
    expected_latency_s: float = 0.0


@dataclass(frozen=True)
class FastTierConfig:
    """Gate configuration for the fast tier.

    * ``latency_budget_s``  -- max expected latency for the fast tier to be used.
    * ``quality_gate``      -- min acceptable fast-tier quality score in [0, 1].
    * ``min_pass_ratio``    -- fraction of benchmarked tasks that must pass BOTH
      gates for the fast tier to be declared eligible overall.
    """

    latency_budget_s: float
    quality_gate: float
    min_pass_ratio: float = 1.0

    def __post_init__(self) -> None:
        if self.latency_budget_s <= 0:
            raise ValueError("latency_budget_s must be positive")
        if not 0.0 <= self.quality_gate <= 1.0:
            raise ValueError("quality_gate must be within [0.0, 1.0]")
        if not 0.0 <= self.min_pass_ratio <= 1.0:
            raise ValueError("min_pass_ratio must be within [0.0, 1.0]")


@dataclass(frozen=True)
class TaskRouteResult:
    """Outcome of routing a single task, including recorded latency + quality."""

    task_id: str
    tier_used: str
    fast_attempted: bool
    fell_back: bool
    reason: str
    latency_s: float
    quality: float
    latency_gate_passed: bool
    quality_gate_passed: bool
    output: str


@dataclass(frozen=True)
class BenchmarkTaskResult:
    """Per-task benchmark record: latency, quality, and both gate verdicts."""

    task_id: str
    latency_s: float
    quality: float
    latency_gate_passed: bool
    quality_gate_passed: bool

    @property
    def passed(self) -> bool:
        """True only when the task clears BOTH gates."""
        return self.latency_gate_passed and self.quality_gate_passed


@dataclass(frozen=True)
class BenchmarkReport:
    """Aggregate fast-tier benchmark over a set of tasks."""

    results: tuple[BenchmarkTaskResult, ...]
    quality_gate: float
    latency_budget_s: float
    min_pass_ratio: float

    @property
    def pass_ratio(self) -> float:
        if not self.results:
            return 0.0
        passed = sum(1 for r in self.results if r.passed)
        return passed / len(self.results)

    @property
    def eligible(self) -> bool:
        """Overall fast-tier eligibility: enough tasks clear both gates."""
        return bool(self.results) and self.pass_ratio >= self.min_pass_ratio

    def result_for(self, task_id: str) -> BenchmarkTaskResult | None:
        for r in self.results:
            if r.task_id == task_id:
                return r
        return None


class ManualClock:
    """A deterministic, injectable clock for hermetic tests.

    ``now`` is the zero-arg reader to pass as the router's ``clock``. ``advance``
    is called by a fake tier runner to model elapsed execution time.
    """

    def __init__(self, start: float = 0.0) -> None:
        self._t = float(start)

    def now(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("cannot advance clock backwards")
        self._t += float(seconds)


class FastTierRouter:
    """Per-task router between a FAST and a STANDARD inference tier.

    The router is fully injected: the fast/standard runners, the quality scorer,
    and the clock all come from the caller, so the routing logic is deterministic
    and testable without any live model.
    """

    def __init__(
        self,
        *,
        config: FastTierConfig,
        fast_runner: TierRunner,
        standard_runner: TierRunner,
        quality_scorer: QualityScorer,
        clock: Clock,
    ) -> None:
        self._config = config
        self._fast_runner = fast_runner
        self._standard_runner = standard_runner
        self._quality_scorer = quality_scorer
        self._clock = clock
        self._history: list[TaskRouteResult] = []

    @property
    def config(self) -> FastTierConfig:
        return self._config

    @property
    def history(self) -> tuple[TaskRouteResult, ...]:
        """All routing decisions made so far, in order."""
        return tuple(self._history)

    @property
    def fallbacks(self) -> tuple[TaskRouteResult, ...]:
        """Routing decisions where the fast tier fell back to standard."""
        return tuple(r for r in self._history if r.fell_back)

    def _timed(self, runner: TierRunner, task: Task) -> tuple[str, float]:
        """Run ``runner`` for ``task``, returning (output, measured_latency_s)."""
        start = self._clock()
        output = runner(task)
        elapsed = self._clock() - start
        # A clock that reads backwards is a caller bug; clamp defensively so a
        # recorded latency is never negative rather than silently propagating it.
        return output, max(0.0, elapsed)

    def route(self, task: Task) -> TaskRouteResult:
        """Route a single task, applying the latency then edit-quality gates."""
        budget = self._config.latency_budget_s
        latency_gate_passed = task.expected_latency_s <= budget

        # -- Latency gate: predicted cost over budget -> never fast-tiered. -----
        if not latency_gate_passed:
            output, latency = self._timed(self._standard_runner, task)
            quality = self._quality_scorer(task, output)
            result = TaskRouteResult(
                task_id=task.task_id,
                tier_used=STANDARD,
                fast_attempted=False,
                fell_back=False,
                reason=REASON_LATENCY_GATE,
                latency_s=latency,
                quality=quality,
                latency_gate_passed=False,
                quality_gate_passed=False,
                output=output,
            )
            self._history.append(result)
            return result

        # -- Fast tier is eligible: run it and measure latency + quality. -------
        fast_output, fast_latency = self._timed(self._fast_runner, task)
        fast_quality = self._quality_scorer(task, fast_output)
        quality_gate_passed = fast_quality >= self._config.quality_gate

        if quality_gate_passed:
            result = TaskRouteResult(
                task_id=task.task_id,
                tier_used=FAST,
                fast_attempted=True,
                fell_back=False,
                reason=REASON_FAST_ACCEPTED,
                latency_s=fast_latency,
                quality=fast_quality,
                latency_gate_passed=True,
                quality_gate_passed=True,
                output=fast_output,
            )
            self._history.append(result)
            return result

        # -- Edit-quality gate breached: fall back to standard, record it. ------
        std_output, std_latency = self._timed(self._standard_runner, task)
        std_quality = self._quality_scorer(task, std_output)
        result = TaskRouteResult(
            task_id=task.task_id,
            tier_used=STANDARD,
            fast_attempted=True,
            fell_back=True,
            reason=REASON_QUALITY_GATE,
            latency_s=std_latency,
            quality=std_quality,
            latency_gate_passed=True,
            quality_gate_passed=False,
            output=std_output,
        )
        self._history.append(result)
        return result

    def benchmark(self, tasks: Iterable[Task]) -> BenchmarkReport:
        """Run ``tasks`` through the FAST tier and grade both gates per task.

        Unlike :meth:`route`, benchmarking always exercises the fast tier so the
        report reflects fast-tier behaviour on every task. The latency gate here
        is judged on the *measured* latency against the budget; the quality gate
        on the fast-tier output score. Overall eligibility is whether the pass
        ratio across both gates clears ``min_pass_ratio``.
        """
        records: list[BenchmarkTaskResult] = []
        for task in tasks:
            output, latency = self._timed(self._fast_runner, task)
            quality = self._quality_scorer(task, output)
            records.append(
                BenchmarkTaskResult(
                    task_id=task.task_id,
                    latency_s=latency,
                    quality=quality,
                    latency_gate_passed=latency <= self._config.latency_budget_s,
                    quality_gate_passed=quality >= self._config.quality_gate,
                )
            )
        return BenchmarkReport(
            results=tuple(records),
            quality_gate=self._config.quality_gate,
            latency_budget_s=self._config.latency_budget_s,
            min_pass_ratio=self._config.min_pass_ratio,
        )


def build_clock_runner(
    clock: ManualClock,
    outputs: dict[str, str],
    latencies: dict[str, float],
    *,
    default_output: str = "",
    default_latency: float = 0.0,
) -> TierRunner:
    """Build a deterministic tier runner backed by a :class:`ManualClock`.

    Handy for tests and offline benchmarking: the returned runner advances
    ``clock`` by the task's configured latency and returns its configured output.
    This is a convenience factory -- callers may inject any ``TierRunner``.
    """

    def _run(task: Task) -> str:
        clock.advance(latencies.get(task.task_id, default_latency))
        return outputs.get(task.task_id, default_output)

    return _run


@dataclass(frozen=True)
class StaticScorer:
    """A deterministic quality scorer keyed by task id (for tests/offline use)."""

    scores: dict[str, float] = field(default_factory=dict)
    default: float = 1.0

    def __call__(self, task: Task, output: str) -> float:
        return self.scores.get(task.task_id, self.default)


def route_all(router: FastTierRouter, tasks: Sequence[Task]) -> list[TaskRouteResult]:
    """Route a sequence of tasks, returning the per-task results in order."""
    return [router.route(task) for task in tasks]
