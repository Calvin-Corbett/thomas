"""CAP-143: Cross-language migration -- differential migration harness.

A migration (legacy module -> rewritten module, or one language -> another) is
only safe if the rewrite is *behaviourally equivalent* to the original over the
inputs that matter. This module provides a **differential migration harness**
that proves -- or disproves -- that equivalence over a corpus, drives a
counterexample-guided retry loop when the rewrite is wrong, and quarantines the
inputs that stubbornly refuse to agree instead of silently passing them.

The harness is deliberately implementation-agnostic. The *source* (legacy) and
*candidate* (migrated) implementations are injected as plain callables --
``Callable[[Any], Any]`` -- so in a real migration each side wraps a subprocess,
an FFI shim, or an imported module, and in tests each side is just a Python
function standing in for e.g. a legacy vs. rewritten unit. Nothing here reaches
out to the network, a clock, or a global; everything is deterministic given the
same corpus and fix step.

Pipeline
--------
1. **Replay the corpus.** Every case is fed to *both* implementations. Each run
   is captured as an :class:`Outcome` -- either a returned value or a raised
   exception signature -- so "raises ``ValueError``" is compared as carefully as
   a return value (a rewrite that returns where the original raised is a
   divergence, not a pass).
2. **Counterexample-driven retry.** On any divergence the harness records a
   :class:`Counterexample` and calls the injected ``fix_step`` to *re-produce*
   the candidate (a new callable). It replays the corpus against the new
   candidate and repeats until the corpus is equivalent or a retry bound is hit.
3. **Quarantine.** Inputs that still diverge after the bound are quarantined as
   first-class :class:`QuarantinedCase` records -- reported, never dropped.
4. **Frozen equivalence suite.** The corpus paired with the source's expected
   outcomes is emitted as a :class:`FrozenSuite` (serialisable to JSON) so the
   target repository can gate future changes on the same behavioural contract.

Tools-layer rule: standard library only; no imports from agent/server/cli.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# A wide but *specific* tuple of concrete exception types. Running a migrated
# implementation can fault in many ways and behavioural equivalence must compare
# those faults -- but we never catch bare ``Exception`` (that would also swallow
# programming errors in the harness itself). ``LookupError`` covers Key/Index;
# ``ArithmeticError`` covers ZeroDivision/Overflow; ``UnicodeError`` is an
# ``OSError``/``ValueError`` subclass kept explicit for clarity.
CAPTURED_EXCEPTIONS: tuple[type[BaseException], ...] = (
    ArithmeticError,
    AttributeError,
    BufferError,
    EOFError,
    LookupError,
    NameError,
    ReferenceError,
    RuntimeError,
    StopIteration,
    TypeError,
    ValueError,
    UnicodeError,
    OSError,
)

# Type aliases for the injected implementations and fix step.
Implementation = Callable[[Any], Any]


class MigrationError(Exception):
    """Base class for migration-harness misuse (bad corpus, bad fix step)."""


@dataclass(frozen=True)
class Outcome:
    """The captured result of running one implementation on one case.

    ``kind`` is ``"return"`` (``value`` holds the returned object) or
    ``"raise"`` (``error`` holds a stable ``"TypeName: message"`` signature).
    Two implementations are equivalent on a case iff their outcomes match under
    the active comparator.
    """

    kind: str
    value: Any = None
    error: str | None = None

    @classmethod
    def returned(cls, value: Any) -> Outcome:
        return cls(kind="return", value=value)

    @classmethod
    def raised(cls, exc: BaseException) -> Outcome:
        return cls(kind="raise", error=f"{type(exc).__name__}: {exc}")

    def to_dict(self) -> dict[str, Any]:
        if self.kind == "raise":
            return {"kind": "raise", "error": self.error}
        return {"kind": "return", "value": repr(self.value)}


@dataclass(frozen=True)
class Divergence:
    """A single case where source and candidate outcomes disagree."""

    input_id: str
    case: Any
    source: Outcome
    candidate: Outcome


@dataclass(frozen=True)
class Counterexample:
    """The first divergence observed on a given retry attempt.

    ``attempt`` is the zero-based attempt index at which this divergence was
    seen (0 = the initial candidate). ``diverging_ids`` is every input that was
    still wrong on that attempt, so the record is both a pinpoint (the
    ``divergence`` field) and a census (how many inputs remained).
    """

    attempt: int
    divergence: Divergence
    diverging_ids: tuple[str, ...]


@dataclass(frozen=True)
class QuarantinedCase:
    """An input that still diverged after the retry bound was exhausted."""

    input_id: str
    case: Any
    source: Outcome
    candidate: Outcome
    attempts: int


@dataclass(frozen=True)
class FrozenCase:
    """One entry of the emitted equivalence suite: input + expected outcome."""

    input_id: str
    case: Any
    expected: Outcome


@dataclass(frozen=True)
class FrozenSuite:
    """The corpus paired with the source's expected outcomes.

    This is the durable behavioural contract for the migrated target: replay it
    against any future candidate to re-prove equivalence. It serialises to a
    stable, ordered JSON document.
    """

    cases: tuple[FrozenCase, ...]

    @property
    def size(self) -> int:
        return len(self.cases)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "size": self.size,
            "cases": [
                {
                    "id": c.input_id,
                    "input": repr(c.case),
                    "expected": c.expected.to_dict(),
                }
                for c in self.cases
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=False)

    def write_json(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.to_json(), encoding="utf-8")
        return target

    def verify(
        self,
        candidate: Implementation,
        *,
        comparator: Callable[[Outcome, Outcome], bool] | None = None,
        runner: Callable[[Implementation, Any], Outcome] | None = None,
    ) -> tuple[str, ...]:
        """Replay the frozen suite against ``candidate``.

        Returns the tuple of input ids that fail to reproduce the expected
        outcome (empty tuple == the candidate honours the frozen contract).
        """

        cmp = comparator or default_comparator
        run = runner or run_capture
        failed: list[str] = []
        for c in self.cases:
            got = run(candidate, c.case)
            if not cmp(c.expected, got):
                failed.append(c.input_id)
        return tuple(failed)


@dataclass(frozen=True)
class FixAttempt:
    """Context handed to the injected ``fix_step`` when a candidate diverges.

    The fix step returns a *new* candidate implementation. It may inspect
    ``divergences`` (the counterexamples) to decide how to re-produce the
    candidate; a converging fix uses them to close the gap.
    """

    attempt: int
    candidate: Implementation
    divergences: tuple[Divergence, ...]


@dataclass(frozen=True)
class MigrationReport:
    """The outcome of a differential migration run."""

    equivalent: bool
    corpus_size: int
    passing_ids: tuple[str, ...]
    quarantined: tuple[QuarantinedCase, ...]
    counterexamples: tuple[Counterexample, ...]
    attempts_used: int
    frozen_suite: FrozenSuite

    @property
    def quarantined_ids(self) -> tuple[str, ...]:
        return tuple(q.input_id for q in self.quarantined)

    def summary(self) -> dict[str, Any]:
        return {
            "equivalent": self.equivalent,
            "corpus_size": self.corpus_size,
            "passing": len(self.passing_ids),
            "quarantined": list(self.quarantined_ids),
            "counterexamples": len(self.counterexamples),
            "attempts_used": self.attempts_used,
        }


def run_capture(impl: Implementation, case: Any) -> Outcome:
    """Run ``impl(case)`` and capture its behaviour as an :class:`Outcome`.

    A returned value and a raised (concrete) exception are both first-class
    outcomes so behavioural equivalence covers the raising behaviour too.
    """

    try:
        return Outcome.returned(impl(case))
    except CAPTURED_EXCEPTIONS as exc:
        logger.debug("captured fault from implementation: %r", exc)
        return Outcome.raised(exc)


def default_comparator(source: Outcome, candidate: Outcome) -> bool:
    """Default behavioural-equivalence check over two outcomes."""

    if source.kind != candidate.kind:
        return False
    if source.kind == "raise":
        return source.error == candidate.error
    return bool(source.value == candidate.value)


def generate_corpus(
    size: int,
    sampler: Callable[[int], Any],
) -> tuple[Any, ...]:
    """Deterministically build a corpus of ``size`` cases from ``sampler``.

    ``sampler`` maps a zero-based index to a case, so the corpus is a pure
    function of ``(size, sampler)`` -- no hidden randomness, fully replayable.
    """

    if size < 0:
        raise MigrationError("corpus size must be non-negative")
    return tuple(sampler(i) for i in range(size))


@dataclass
class MigrationHarness:
    """Differential migration harness.

    Configure the retry bound and (optionally) inject a custom comparator or
    runner, then call :meth:`run` with the source, the initial candidate, the
    corpus, and a fix step.
    """

    max_retries: int = 3
    comparator: Callable[[Outcome, Outcome], bool] = field(default=default_comparator)
    runner: Callable[[Implementation, Any], Outcome] = field(default=run_capture)

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise MigrationError("max_retries must be non-negative")

    def _evaluate(
        self,
        source: Implementation,
        candidate: Implementation,
        corpus: Sequence[tuple[str, Any]],
    ) -> tuple[dict[str, Outcome], list[Divergence]]:
        """Replay the corpus, returning source outcomes and any divergences."""

        source_outcomes: dict[str, Outcome] = {}
        divergences: list[Divergence] = []
        for input_id, case in corpus:
            src = self.runner(source, case)
            source_outcomes[input_id] = src
            cand = self.runner(candidate, case)
            if not self.comparator(src, cand):
                divergences.append(
                    Divergence(
                        input_id=input_id,
                        case=case,
                        source=src,
                        candidate=cand,
                    )
                )
        return source_outcomes, divergences

    def run(
        self,
        source: Implementation,
        candidate: Implementation,
        corpus: Iterable[Any],
        *,
        fix_step: Callable[[FixAttempt], Implementation] | None = None,
    ) -> MigrationReport:
        """Prove source/candidate equivalence over ``corpus``.

        Divergences trigger ``fix_step`` (if given) to re-produce the candidate,
        looping up to ``max_retries`` times. Inputs still diverging after the
        bound are quarantined. A :class:`FrozenSuite` of the corpus + expected
        (source) outcomes is always emitted.
        """

        # Materialise the corpus once with stable, index-derived ids so ids are
        # identical across every retry -- the harness is deterministic.
        indexed: list[tuple[str, Any]] = [(f"case-{i:04d}", case) for i, case in enumerate(corpus)]

        current = candidate
        attempts_used = 0
        counterexamples: list[Counterexample] = []

        source_outcomes, divergences = self._evaluate(source, current, indexed)

        while divergences:
            counterexamples.append(
                Counterexample(
                    attempt=attempts_used,
                    divergence=divergences[0],
                    diverging_ids=tuple(d.input_id for d in divergences),
                )
            )
            if fix_step is None or attempts_used >= self.max_retries:
                break
            current = fix_step(
                FixAttempt(
                    attempt=attempts_used,
                    candidate=current,
                    divergences=tuple(divergences),
                )
            )
            if not callable(current):
                raise MigrationError("fix_step must return a callable candidate")
            attempts_used += 1
            source_outcomes, divergences = self._evaluate(source, current, indexed)

        diverging_ids = {d.input_id for d in divergences}
        passing_ids = tuple(input_id for input_id, _ in indexed if input_id not in diverging_ids)
        quarantined = tuple(
            QuarantinedCase(
                input_id=d.input_id,
                case=d.case,
                source=d.source,
                candidate=d.candidate,
                attempts=attempts_used,
            )
            for d in divergences
        )
        frozen_suite = FrozenSuite(
            cases=tuple(
                FrozenCase(
                    input_id=input_id,
                    case=case,
                    expected=source_outcomes[input_id],
                )
                for input_id, case in indexed
            )
        )

        return MigrationReport(
            equivalent=not divergences,
            corpus_size=len(indexed),
            passing_ids=passing_ids,
            quarantined=quarantined,
            counterexamples=tuple(counterexamples),
            attempts_used=attempts_used,
            frozen_suite=frozen_suite,
        )


def prove_migration(
    source: Implementation,
    candidate: Implementation,
    corpus: Iterable[Any],
    *,
    fix_step: Callable[[FixAttempt], Implementation] | None = None,
    max_retries: int = 3,
    comparator: Callable[[Outcome, Outcome], bool] | None = None,
) -> MigrationReport:
    """Convenience wrapper: build a :class:`MigrationHarness` and run once."""

    harness = MigrationHarness(
        max_retries=max_retries,
        comparator=comparator or default_comparator,
    )
    return harness.run(source, candidate, corpus, fix_step=fix_step)
