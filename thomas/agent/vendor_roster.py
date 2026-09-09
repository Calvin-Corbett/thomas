"""Cross-vendor agent hosting: a roster of agent runtimes and a shared scorecard.

Thomas can host more than its own internal agent loop. Teams routinely want to
put an external vendor's agent runtime (a hosted Claude/GPT/Gemini agent, a
partner's in-house agent, a local model server) on the same footing as the
built-in runtime and ask a single, boring question: *given the same tasks and
the same metrics, which one wins?*

This module answers that question deterministically.

Two pieces
----------
:class:`VendorRoster`
    Registers agent **runtimes** by name. Each runtime carries a ``vendor``
    label, an ``origin`` (:data:`ORIGIN_INTERNAL` for Thomas's own runtime,
    :data:`ORIGIN_EXTERNAL` for a hosted/partner runtime), and an *injectable*
    ``invoke`` adapter (``Callable[[Task], InvocationResult]``). The roster owns
    no vendor SDKs and makes no network calls — the adapter is the only door to
    the outside world, so tests inject fakes and production injects real HTTP
    clients through the exact same seam.

:meth:`VendorRoster.run_scorecard`
    Runs the **same** task set through **every** registered runtime and scores
    each one on **identical** metrics — success rate, latency, token usage,
    cost, and quality (via an injectable scorer) — then ranks them with a
    documented composite formula. A runtime whose adapter fails on a task is
    *scored* (that task counts as a failure, quality 0) rather than allowed to
    crash the whole comparison.

Determinism
-----------
Nothing here reads the wall clock or the network on its own. Latency comes from
an injected ``clock`` (adapters advance it), quality comes from an injected
``scorer``, and every aggregation and ranking tie-break is total and stable
(ties break by runtime name). Same inputs → same :class:`ScorecardReport`,
every time.
"""

from __future__ import annotations

import dataclasses
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

ORIGIN_INTERNAL = "internal"
ORIGIN_EXTERNAL = "external"
_VALID_ORIGINS = (ORIGIN_INTERNAL, ORIGIN_EXTERNAL)


class RuntimeInvocationError(RuntimeError):
    """Raised by an ``invoke`` adapter to signal a task-level failure.

    Adapters should raise this (or one of the standard I/O errors caught by the
    scorecard) to mark a task as failed. The scorecard records the failure and
    keeps comparing the other runtimes instead of propagating the error.
    """


# Exceptions an adapter may raise that the scorecard treats as a *scored*
# task failure rather than a crash. Kept as an explicit, specific tuple (no
# broad ``except Exception``): a genuinely unexpected error type still
# propagates so real bugs are never silently swallowed.
_ADAPTER_FAILURE_ERRORS: tuple[type[BaseException], ...] = (
    RuntimeInvocationError,
    TimeoutError,
    ConnectionError,
    OSError,
    ValueError,
)


@dataclasses.dataclass(frozen=True)
class Task:
    """One unit of work fed identically to every registered runtime."""

    task_id: str
    prompt: str = ""
    reference: Any = None  # optional gold answer / rubric the scorer may use
    meta: Mapping[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(frozen=True)
class InvocationResult:
    """What an ``invoke`` adapter returns for a single task.

    tokens and cost are non-negative usage figures reported by the runtime.
    ``succeeded=False`` lets an adapter report a soft failure (task completed
    but produced an unusable answer) without raising.
    """

    output: Any = None
    tokens: int = 0
    cost: float = 0.0
    succeeded: bool = True


@dataclasses.dataclass(frozen=True)
class AgentRuntime:
    """A registered agent runtime — internal or external — plus its adapter."""

    name: str
    vendor: str
    origin: str
    invoke: Callable[[Task], InvocationResult]

    @property
    def is_external(self) -> bool:
        return self.origin == ORIGIN_EXTERNAL


@dataclasses.dataclass(frozen=True)
class TaskScore:
    """Per-runtime, per-task record. Identical shape for every runtime."""

    task_id: str
    succeeded: bool
    latency: float
    tokens: int
    cost: float
    quality: float
    error: str | None = None


@dataclasses.dataclass(frozen=True)
class RuntimeMetrics:
    """Aggregated identical metrics for one runtime over the task set."""

    task_count: int
    success_rate: float
    avg_latency: float
    total_tokens: int
    avg_tokens: float
    total_cost: float
    avg_cost: float
    avg_quality: float


@dataclasses.dataclass(frozen=True)
class RuntimeScorecard:
    """One runtime's full result: identity, metrics, per-task detail, score."""

    name: str
    vendor: str
    origin: str
    metrics: RuntimeMetrics
    task_scores: tuple[TaskScore, ...]
    composite: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "vendor": self.vendor,
            "origin": self.origin,
            "composite": self.composite,
            "metrics": dataclasses.asdict(self.metrics),
            "task_scores": [dataclasses.asdict(ts) for ts in self.task_scores],
        }


@dataclasses.dataclass(frozen=True)
class ScorecardConfig:
    """Weights for the composite ranking score.

    Every weight applies to a metric normalized into a [0, 1] "goodness" value
    (see :func:`_normalize_lower_better`), so the composite is itself in
    [0, 1]. ``success_rate`` and ``quality`` are already goodness values;
    latency, cost, and tokens are "lower is better" and are inverted relative
    to the runtimes being compared. Weights need not sum to 1 — the composite
    is divided by the total weight, so only their *ratios* matter.
    """

    success_weight: float = 0.40
    quality_weight: float = 0.30
    latency_weight: float = 0.10
    cost_weight: float = 0.10
    tokens_weight: float = 0.10

    def total_weight(self) -> float:
        return self.success_weight + self.quality_weight + self.latency_weight + self.cost_weight + self.tokens_weight


# A scorer maps (task, output) -> quality in [0, 1]. Injected; deterministic.
Scorer = Callable[[Task, Any], float]


def unit_scorer(_task: Task, _output: Any) -> float:
    """Default scorer: full quality for any produced output.

    With this scorer, quality mirrors success (a failed task never reaches the
    scorer and is recorded as quality 0), so a roster works out of the box
    without a domain rubric. Inject a real scorer to grade answer content.
    """

    return 1.0


def _clamp01(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


class ScorecardReport:
    """Ranked comparison of every runtime over one shared task set."""

    def __init__(self, cards: Sequence[RuntimeScorecard], tasks: Sequence[Task]) -> None:
        # Rank: highest composite first, ties broken by name (stable + total).
        self._cards: tuple[RuntimeScorecard, ...] = tuple(sorted(cards, key=lambda c: (-c.composite, c.name)))
        self._by_name: dict[str, RuntimeScorecard] = {c.name: c for c in self._cards}
        self._task_ids: tuple[str, ...] = tuple(t.task_id for t in tasks)

    @property
    def cards(self) -> tuple[RuntimeScorecard, ...]:
        """Scorecards in ranked order (best first)."""
        return self._cards

    @property
    def task_ids(self) -> tuple[str, ...]:
        return self._task_ids

    def ranking(self) -> tuple[str, ...]:
        """Runtime names in ranked order, best first."""
        return tuple(c.name for c in self._cards)

    def rank_of(self, name: str) -> int:
        """1-based rank of a runtime by name (raises KeyError if absent)."""
        for idx, card in enumerate(self._cards, start=1):
            if card.name == name:
                return idx
        raise KeyError(name)

    def card(self, name: str) -> RuntimeScorecard:
        return self._by_name[name]

    @property
    def winner(self) -> RuntimeScorecard | None:
        return self._cards[0] if self._cards else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_ids": list(self._task_ids),
            "ranking": list(self.ranking()),
            "cards": [c.to_dict() for c in self._cards],
        }


def _normalize_lower_better(value: float, lo: float, hi: float) -> float:
    """Map a 'lower is better' metric to [0, 1] goodness within [lo, hi].

    Best (== lo) -> 1.0, worst (== hi) -> 0.0. When every runtime ties
    (hi == lo) the metric is non-discriminating, so all get full goodness.
    """

    if hi <= lo:
        return 1.0
    return _clamp01((hi - value) / (hi - lo))


class VendorRoster:
    """Registry of internal + external agent runtimes with a shared scorecard."""

    def __init__(self, *, clock: Callable[[], float] | None = None) -> None:
        self._runtimes: dict[str, AgentRuntime] = {}
        self._clock: Callable[[], float] = clock or time.monotonic

    # -- registration --------------------------------------------------------

    def register(
        self,
        name: str,
        *,
        vendor: str,
        invoke: Callable[[Task], InvocationResult],
        origin: str = ORIGIN_EXTERNAL,
    ) -> AgentRuntime:
        """Add (or replace) a runtime. Returns the registered runtime.

        ``origin`` must be :data:`ORIGIN_INTERNAL` or :data:`ORIGIN_EXTERNAL`.
        Registering an existing name replaces it (roster stays a set keyed by
        name), which is how a runtime is swapped for a newer adapter.
        """

        if not name:
            raise ValueError("runtime name must be non-empty")
        if origin not in _VALID_ORIGINS:
            raise ValueError(f"origin must be one of {_VALID_ORIGINS}, got {origin!r}")
        if not callable(invoke):
            raise TypeError("invoke adapter must be callable")
        runtime = AgentRuntime(name=name, vendor=vendor, origin=origin, invoke=invoke)
        self._runtimes[name] = runtime
        return runtime

    def register_internal(
        self,
        name: str,
        *,
        vendor: str = "thomas",
        invoke: Callable[[Task], InvocationResult],
    ) -> AgentRuntime:
        """Convenience wrapper for registering Thomas's own runtime."""

        return self.register(name, vendor=vendor, invoke=invoke, origin=ORIGIN_INTERNAL)

    def unregister(self, name: str) -> bool:
        """Remove a runtime by name. Returns True if it was present."""

        return self._runtimes.pop(name, None) is not None

    def get(self, name: str) -> AgentRuntime | None:
        return self._runtimes.get(name)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._runtimes))

    def runtimes(self) -> tuple[AgentRuntime, ...]:
        """All registered runtimes, ordered by name (deterministic)."""

        return tuple(self._runtimes[n] for n in sorted(self._runtimes))

    def __len__(self) -> int:
        return len(self._runtimes)

    def __contains__(self, name: object) -> bool:
        return name in self._runtimes

    # -- execution -----------------------------------------------------------

    def _run_one_task(self, runtime: AgentRuntime, task: Task, scorer: Scorer) -> TaskScore:
        """Invoke one runtime on one task, measuring identical metrics.

        A failure raised by the adapter (from :data:`_ADAPTER_FAILURE_ERRORS`)
        is captured as a scored failure — latency is still recorded, tokens and
        cost are 0, quality is 0 — so one bad runtime never aborts the run.
        """

        started = self._clock()
        try:
            result = runtime.invoke(task)
        except _ADAPTER_FAILURE_ERRORS as exc:
            latency = max(0.0, self._clock() - started)
            return TaskScore(
                task_id=task.task_id,
                succeeded=False,
                latency=latency,
                tokens=0,
                cost=0.0,
                quality=0.0,
                error=f"{type(exc).__name__}: {exc}",
            )
        latency = max(0.0, self._clock() - started)
        if not isinstance(result, InvocationResult):
            raise TypeError(
                f"runtime {runtime.name!r} adapter returned {type(result).__name__}, expected InvocationResult"
            )
        if not result.succeeded:
            return TaskScore(
                task_id=task.task_id,
                succeeded=False,
                latency=latency,
                tokens=max(0, int(result.tokens)),
                cost=max(0.0, float(result.cost)),
                quality=0.0,
                error="runtime reported unsuccessful result",
            )
        quality = _clamp01(float(scorer(task, result.output)))
        return TaskScore(
            task_id=task.task_id,
            succeeded=True,
            latency=latency,
            tokens=max(0, int(result.tokens)),
            cost=max(0.0, float(result.cost)),
            quality=quality,
        )

    @staticmethod
    def _aggregate(task_scores: Sequence[TaskScore]) -> RuntimeMetrics:
        n = len(task_scores)
        if n == 0:
            return RuntimeMetrics(0, 0.0, 0.0, 0, 0.0, 0.0, 0.0, 0.0)
        successes = sum(1 for ts in task_scores if ts.succeeded)
        total_latency = sum(ts.latency for ts in task_scores)
        total_tokens = sum(ts.tokens for ts in task_scores)
        total_cost = sum(ts.cost for ts in task_scores)
        total_quality = sum(ts.quality for ts in task_scores)
        return RuntimeMetrics(
            task_count=n,
            success_rate=successes / n,
            avg_latency=total_latency / n,
            total_tokens=total_tokens,
            avg_tokens=total_tokens / n,
            total_cost=total_cost,
            avg_cost=total_cost / n,
            avg_quality=total_quality / n,
        )

    def run_scorecard(
        self,
        tasks: Iterable[Task],
        *,
        scorer: Scorer | None = None,
        config: ScorecardConfig | None = None,
    ) -> ScorecardReport:
        """Run the shared task set through every runtime and rank them.

        The same ``tasks`` are executed against every registered runtime and
        scored on the same metrics, so the resulting :class:`ScorecardReport`
        compares like with like. Requires at least one registered runtime and a
        non-empty task set.
        """

        task_list = list(tasks)
        if not task_list:
            raise ValueError("scorecard requires at least one task")
        if not self._runtimes:
            raise ValueError("scorecard requires at least one registered runtime")
        score = scorer or unit_scorer
        cfg = config or ScorecardConfig()

        # Deterministic iteration order (by name) so per-task clock advances
        # accrue identically across runs.
        runtimes = self.runtimes()
        per_runtime_scores: dict[str, list[TaskScore]] = {}
        metrics: dict[str, RuntimeMetrics] = {}
        for runtime in runtimes:
            scores = [self._run_one_task(runtime, task, score) for task in task_list]
            per_runtime_scores[runtime.name] = scores
            metrics[runtime.name] = self._aggregate(scores)

        composites = self._composite_scores(metrics, cfg)
        cards = [
            RuntimeScorecard(
                name=rt.name,
                vendor=rt.vendor,
                origin=rt.origin,
                metrics=metrics[rt.name],
                task_scores=tuple(per_runtime_scores[rt.name]),
                composite=composites[rt.name],
            )
            for rt in runtimes
        ]
        return ScorecardReport(cards, task_list)

    @staticmethod
    def _composite_scores(metrics: Mapping[str, RuntimeMetrics], cfg: ScorecardConfig) -> dict[str, float]:
        """Weighted composite in [0, 1] per runtime (higher is better).

        latency/cost/tokens are normalized as 'lower is better' relative to the
        set; success_rate and quality are used directly. The composite is the
        weighted average of the five goodness values.
        """

        names = list(metrics)
        lat_lo = min(m.avg_latency for m in metrics.values())
        lat_hi = max(m.avg_latency for m in metrics.values())
        cost_lo = min(m.avg_cost for m in metrics.values())
        cost_hi = max(m.avg_cost for m in metrics.values())
        tok_lo = min(m.avg_tokens for m in metrics.values())
        tok_hi = max(m.avg_tokens for m in metrics.values())
        total_w = cfg.total_weight()
        if total_w <= 0.0:
            raise ValueError("ScorecardConfig weights must sum to a positive value")

        out: dict[str, float] = {}
        for name in names:
            m = metrics[name]
            latency_good = _normalize_lower_better(m.avg_latency, lat_lo, lat_hi)
            cost_good = _normalize_lower_better(m.avg_cost, cost_lo, cost_hi)
            tokens_good = _normalize_lower_better(m.avg_tokens, tok_lo, tok_hi)
            weighted = (
                cfg.success_weight * m.success_rate
                + cfg.quality_weight * m.avg_quality
                + cfg.latency_weight * latency_good
                + cfg.cost_weight * cost_good
                + cfg.tokens_weight * tokens_good
            )
            out[name] = _clamp01(weighted / total_w)
        return out
