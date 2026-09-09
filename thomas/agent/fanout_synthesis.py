"""Parallel fan-out from one prompt with conflict-aware synthesis (stdlib-only).

This module answers a single question by fanning *one* prompt out to ``N``
**independent** workers (default ``N = 6``) and then synthesizing their
answers in a way that is honest about disagreement.

Two properties are load-bearing and enforced by the tests:

Independence
    Every worker receives the *same* prompt but runs in isolation and returns
    its *own* :class:`Evidence` record. The synthesizer never shares mutable
    state between worker calls: each call gets a fresh :class:`WorkerRequest`
    and its output is stamped with that request's identity. After a fan-out you
    can therefore assert ``len({e.worker_id for e in result.evidence_records})
    == N`` -- one distinct evidence record per worker for a single prompt.

Conflict-awareness (no silent majority pick)
    Results are grouped by *normalized answer*. If every worker agrees the
    outcome is :attr:`Outcome.CONSENSUS` and a synthesized ``answer`` is
    produced. If workers **materially disagree** (more than one answer group),
    the default policy does **not** silently pick the plurality: it returns
    :attr:`Outcome.CONFLICT` with ``answer is None`` and an explicit
    :class:`ConflictReport` naming which workers are on which side and carrying
    each side's supporting evidence. A caller who wants a majority to *resolve*
    a split must opt in by lowering :attr:`SynthesisConfig.consensus_threshold`
    below ``1.0``; that yields :attr:`Outcome.SUPERMAJORITY`, which still
    records the dissent rather than hiding it.

Everything is deterministic given fixed worker outputs -- no live model, no
network, no wall-clock or randomness in the synthesis path. Worker *ordering*
is preserved (``worker-0`` .. ``worker-{N-1}``) and answer groups are ranked by
``(support desc, first-seen index asc)`` so identical inputs always produce
byte-identical reports.

The worker is fully injectable, so this module is trivially testable and does
not depend on the swarm, an LLM client, or any other subsystem.
"""

from __future__ import annotations

import dataclasses
import enum
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

__all__ = [
    "DEFAULT_FANOUT",
    "Evidence",
    "WorkerRequest",
    "WorkerResult",
    "ClaimGroup",
    "ConflictReport",
    "Outcome",
    "SynthesisConfig",
    "SynthesisResult",
    "FanoutSynthesizer",
    "default_normalizer",
    "fan_out_and_synthesize",
]

DEFAULT_FANOUT = 6

_WHITESPACE = re.compile(r"\s+")


def default_normalizer(answer: str) -> str:
    """Case/whitespace-insensitive normalization used to group equal answers.

    Trivial formatting differences ("Yes." vs " yes ") collapse to the same
    key so they count as *agreement*; genuinely different claims stay distinct.
    """

    return _WHITESPACE.sub(" ", str(answer).strip()).casefold()


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Evidence:
    """One worker's independent support for its answer.

    ``worker_id`` ties the evidence back to the worker that produced it; the
    synthesizer re-stamps this field from the request so a fan-out always
    yields exactly one evidence record per worker id.
    """

    worker_id: str
    summary: str = ""
    sources: tuple[str, ...] = ()
    detail: Mapping[str, Any] | None = None


@dataclasses.dataclass(frozen=True)
class WorkerRequest:
    """The isolated unit of work handed to a single worker.

    Every worker in a fan-out receives an equal ``prompt`` and a unique
    ``worker_id``/``index``. Nothing else is shared, which is what makes the
    workers independent.
    """

    prompt: str
    worker_id: str
    index: int


@dataclasses.dataclass(frozen=True)
class WorkerResult:
    """A single worker's answer plus the evidence it stands on.

    ``prompt`` records exactly what this worker was asked, so independence can
    be proven (all workers saw the same prompt, each produced its own
    evidence).
    """

    worker_id: str
    index: int
    prompt: str
    answer: str
    evidence: Evidence


@dataclasses.dataclass(frozen=True)
class ClaimGroup:
    """A set of workers that produced the same (normalized) answer.

    ``answer`` is the representative raw answer (the first worker's, in worker
    order). ``worker_ids`` and ``evidence`` are aligned and carry every
    worker's supporting evidence for this side.
    """

    normalized: str
    answer: str
    worker_ids: tuple[str, ...]
    evidence: tuple[Evidence, ...]
    first_index: int

    @property
    def support(self) -> int:
        """Number of workers backing this answer."""

        return len(self.worker_ids)


@dataclasses.dataclass(frozen=True)
class ConflictReport:
    """Explicit account of a disagreement across the fan-out.

    ``groups`` are ranked most-supported first. ``resolved`` is ``True`` only
    when a configured supermajority threshold cleared the split; otherwise the
    conflict is unresolved and the synthesized answer is deliberately withheld.
    """

    groups: tuple[ClaimGroup, ...]
    resolved: bool
    total_workers: int

    @property
    def majority(self) -> ClaimGroup:
        """The best-supported side (first, since groups are pre-ranked)."""

        return self.groups[0]

    @property
    def dissenting_worker_ids(self) -> tuple[str, ...]:
        """Workers not in the best-supported side, in worker order."""

        losers: list[str] = []
        for group in self.groups[1:]:
            losers.extend(group.worker_ids)
        return tuple(losers)

    def describe(self) -> str:
        """Human-readable, deterministic one-line-per-side conflict summary."""

        status = "RESOLVED by threshold" if self.resolved else "UNRESOLVED"
        lines = [f"conflict ({status}) across {self.total_workers} workers:"]
        for rank, group in enumerate(self.groups):
            members = ", ".join(group.worker_ids)
            lines.append(f"  side {rank + 1}: {group.support} worker(s) [{members}] -> {group.answer!r}")
        return "\n".join(lines)


class Outcome(enum.Enum):
    """How the fan-out resolved."""

    CONSENSUS = "consensus"  # unanimous agreement
    SUPERMAJORITY = "supermajority"  # split, but a side cleared the threshold
    CONFLICT = "conflict"  # material disagreement, deliberately unresolved


@dataclasses.dataclass(frozen=True)
class SynthesisConfig:
    """Policy knobs for turning worker results into a synthesized answer.

    consensus_threshold: fraction (0, 1] of workers that must back a single
        answer for it to count as resolved. The default ``1.0`` demands
        unanimity, so *any* split is reported as an unresolved conflict rather
        than being silently majority-picked. Lower it (e.g. ``0.66``) to let a
        supermajority resolve a split -- the dissent is still recorded.
    """

    consensus_threshold: float = 1.0

    def __post_init__(self) -> None:
        if not (0.0 < self.consensus_threshold <= 1.0):
            raise ValueError("consensus_threshold must be in the interval (0, 1]")


@dataclasses.dataclass(frozen=True)
class SynthesisResult:
    """The synthesized outcome of one fan-out, plus every worker's raw result."""

    outcome: Outcome
    prompt: str
    answer: str | None
    groups: tuple[ClaimGroup, ...]
    consensus_group: ClaimGroup | None
    conflict: ConflictReport | None
    worker_results: tuple[WorkerResult, ...]
    threshold: float

    @property
    def is_consensus(self) -> bool:
        return self.outcome is Outcome.CONSENSUS

    @property
    def is_conflict(self) -> bool:
        return self.outcome is Outcome.CONFLICT

    @property
    def resolved(self) -> bool:
        """True when a synthesized answer was produced (consensus/supermajority)."""

        return self.answer is not None

    @property
    def worker_count(self) -> int:
        return len(self.worker_results)

    @property
    def evidence_records(self) -> tuple[Evidence, ...]:
        """Each worker's independent evidence, in worker order."""

        return tuple(r.evidence for r in self.worker_results)

    @property
    def prompts_seen(self) -> tuple[str, ...]:
        """The prompt each worker actually received (all equal by construction)."""

        return tuple(r.prompt for r in self.worker_results)

    def dissenting_worker_ids(self) -> tuple[str, ...]:
        """Workers outside the winning side; empty on unanimous consensus."""

        if self.conflict is None:
            return ()
        return self.conflict.dissenting_worker_ids

    def describe(self) -> str:
        """Deterministic human-readable synthesis summary."""

        if self.outcome is Outcome.CONSENSUS:
            group = self.consensus_group
            assert group is not None  # invariant for CONSENSUS
            members = ", ".join(group.worker_ids)
            return f"consensus of {group.support} workers [{members}] -> {self.answer!r}"
        if self.outcome is Outcome.SUPERMAJORITY:
            assert self.conflict is not None
            head = f"supermajority answer {self.answer!r} (threshold {self.threshold})"
            return head + "\n" + self.conflict.describe()
        # CONFLICT
        assert self.conflict is not None
        return "no consensus; answer withheld\n" + self.conflict.describe()


# ---------------------------------------------------------------------------
# Fan-out + synthesis engine
# ---------------------------------------------------------------------------

WorkerCallable = Callable[[WorkerRequest], Any]


class FanoutSynthesizer:
    """Fan one prompt out to ``fanout`` independent workers, then synthesize.

    The ``worker`` callable receives a :class:`WorkerRequest` and must return
    either a :class:`WorkerResult`, or a mapping with an ``"answer"`` key and an
    optional ``"evidence"`` value (an :class:`Evidence`, a mapping, or a plain
    string). The synthesizer stamps the returned result with the request's
    ``worker_id``/``prompt``/``index`` so worker identity is authoritative and
    independence is provable regardless of what the worker fills in.

    Worker exceptions are intentionally *not* swallowed: a worker is expected
    to return a result, and letting failures propagate keeps the fan-out
    deterministic and free of broad exception handling.
    """

    def __init__(
        self,
        worker: WorkerCallable,
        *,
        fanout: int = DEFAULT_FANOUT,
        worker_ids: Sequence[str] | None = None,
        normalizer: Callable[[str], str] | None = None,
        config: SynthesisConfig | None = None,
    ) -> None:
        if not callable(worker):
            raise TypeError("worker must be callable")
        if worker_ids is not None:
            ids = tuple(str(w) for w in worker_ids)
            if not ids:
                raise ValueError("worker_ids must be non-empty")
            if len(set(ids)) != len(ids):
                raise ValueError("worker_ids must be unique")
            self._worker_ids = ids
        else:
            if fanout < 1:
                raise ValueError("fanout must be >= 1")
            self._worker_ids = tuple(f"worker-{i}" for i in range(fanout))
        self._worker = worker
        self._normalizer = normalizer or default_normalizer
        self._config = config or SynthesisConfig()

    @property
    def fanout(self) -> int:
        """Number of workers this synthesizer fans out to."""

        return len(self._worker_ids)

    @property
    def worker_ids(self) -> tuple[str, ...]:
        return self._worker_ids

    @property
    def config(self) -> SynthesisConfig:
        return self._config

    # -- fan-out -------------------------------------------------------------

    def fan_out(self, prompt: str) -> tuple[WorkerResult, ...]:
        """Run every worker once on ``prompt`` and return their results.

        Each worker is invoked with a fresh :class:`WorkerRequest`; no state is
        carried between calls, so the workers are independent.
        """

        results: list[WorkerResult] = []
        for index, worker_id in enumerate(self._worker_ids):
            request = WorkerRequest(prompt=prompt, worker_id=worker_id, index=index)
            raw = self._worker(request)
            results.append(self._coerce(request, raw))
        return tuple(results)

    def _coerce(self, request: WorkerRequest, raw: Any) -> WorkerResult:
        """Normalize a worker's return value into a stamped :class:`WorkerResult`."""

        if isinstance(raw, WorkerResult):
            answer = raw.answer
            evidence = raw.evidence
        elif isinstance(raw, Mapping):
            if "answer" not in raw:
                raise ValueError(f"worker {request.worker_id!r} returned a mapping without an 'answer' key")
            answer = raw["answer"]
            evidence = raw.get("evidence")
        else:
            raise TypeError(
                f"worker {request.worker_id!r} returned unsupported type "
                f"{type(raw).__name__}; expected WorkerResult or mapping"
            )
        return WorkerResult(
            worker_id=request.worker_id,
            index=request.index,
            prompt=request.prompt,
            answer=str(answer),
            evidence=self._coerce_evidence(request.worker_id, evidence),
        )

    @staticmethod
    def _coerce_evidence(worker_id: str, raw: Any) -> Evidence:
        """Build an :class:`Evidence` stamped with ``worker_id``."""

        if isinstance(raw, Evidence):
            # Re-stamp worker_id so evidence identity always matches the worker.
            return dataclasses.replace(raw, worker_id=worker_id)
        if isinstance(raw, Mapping):
            sources = raw.get("sources") or ()
            detail = raw.get("detail")
            return Evidence(
                worker_id=worker_id,
                summary=str(raw.get("summary", "")),
                sources=tuple(str(s) for s in sources),
                detail=detail if isinstance(detail, Mapping) else None,
            )
        if raw is None:
            return Evidence(worker_id=worker_id)
        return Evidence(worker_id=worker_id, summary=str(raw))

    # -- synthesis -----------------------------------------------------------

    def synthesize(self, prompt: str, results: Sequence[WorkerResult]) -> SynthesisResult:
        """Combine worker ``results`` into a conflict-aware synthesis."""

        if not results:
            raise ValueError("cannot synthesize an empty result set")
        groups = self._group(results)
        total = len(results)

        if len(groups) == 1:
            only = groups[0]
            return SynthesisResult(
                outcome=Outcome.CONSENSUS,
                prompt=prompt,
                answer=only.answer,
                groups=groups,
                consensus_group=only,
                conflict=None,
                worker_results=tuple(results),
                threshold=self._config.consensus_threshold,
            )

        # Materially split: rank sides and decide whether a threshold resolves it.
        top = groups[0]
        top_fraction = top.support / total
        threshold = self._config.consensus_threshold
        # Unanimity (threshold == 1.0) can never be met here (len(groups) > 1),
        # so the default policy always falls through to CONFLICT.
        if threshold < 1.0 and top_fraction >= threshold:
            return SynthesisResult(
                outcome=Outcome.SUPERMAJORITY,
                prompt=prompt,
                answer=top.answer,
                groups=groups,
                consensus_group=top,
                conflict=ConflictReport(groups=groups, resolved=True, total_workers=total),
                worker_results=tuple(results),
                threshold=threshold,
            )
        return SynthesisResult(
            outcome=Outcome.CONFLICT,
            prompt=prompt,
            answer=None,
            groups=groups,
            consensus_group=None,
            conflict=ConflictReport(groups=groups, resolved=False, total_workers=total),
            worker_results=tuple(results),
            threshold=threshold,
        )

    def _group(self, results: Sequence[WorkerResult]) -> tuple[ClaimGroup, ...]:
        """Group results by normalized answer, ranked (support desc, first asc)."""

        buckets: dict[str, dict[str, Any]] = {}
        for result in results:
            key = self._normalizer(result.answer)
            bucket = buckets.get(key)
            if bucket is None:
                buckets[key] = {
                    "answer": result.answer,
                    "worker_ids": [result.worker_id],
                    "evidence": [result.evidence],
                    "first_index": result.index,
                }
            else:
                bucket["worker_ids"].append(result.worker_id)
                bucket["evidence"].append(result.evidence)

        groups = [
            ClaimGroup(
                normalized=key,
                answer=bucket["answer"],
                worker_ids=tuple(bucket["worker_ids"]),
                evidence=tuple(bucket["evidence"]),
                first_index=bucket["first_index"],
            )
            for key, bucket in buckets.items()
        ]
        groups.sort(key=lambda g: (-g.support, g.first_index))
        return tuple(groups)

    # -- one-shot ------------------------------------------------------------

    def run(self, prompt: str) -> SynthesisResult:
        """Fan ``prompt`` out to all workers and synthesize their results."""

        return self.synthesize(prompt, self.fan_out(prompt))


def fan_out_and_synthesize(
    prompt: str,
    worker: WorkerCallable,
    *,
    fanout: int = DEFAULT_FANOUT,
    worker_ids: Sequence[str] | None = None,
    normalizer: Callable[[str], str] | None = None,
    config: SynthesisConfig | None = None,
) -> SynthesisResult:
    """Convenience wrapper: build a :class:`FanoutSynthesizer` and run it once."""

    return FanoutSynthesizer(
        worker,
        fanout=fanout,
        worker_ids=worker_ids,
        normalizer=normalizer,
        config=config,
    ).run(prompt)
