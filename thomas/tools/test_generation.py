"""Requirement-linked test generation with mutation-testing validation.

This module turns a small declarative *specification* of a target function into
a set of concrete, requirement-linked test cases, then validates the quality of
that generated suite with **mutation testing** -- running the suite against
deliberately perturbed copies of the function ("mutants") and measuring how many
the suite is able to detect.

Two capabilities, both stdlib-only and hermetic:

1. **Requirement-linked generation** (:func:`generate_tests`). Given a
   :class:`FunctionSpec` (the correct function plus an optional reference
   *oracle*) and a list of :class:`Requirement` objects, produce a
   :class:`GeneratedSuite` of :class:`GeneratedTest` cases. Every generated test
   is *linked* to a requirement id and is classified as either an ``edge`` case
   (a boundary input such as ``0``, an empty collection, or a maximum value) or
   a ``failure`` case (an invalid input that must raise). Expected values for
   edge cases are *computed* from the oracle; failure cases assert that the
   declared exception type is raised. Generation validates the spec is
   self-consistent, so the generated suite always passes against the correct
   function.

2. **Mutation-testing validation** (:func:`mutation_test`). Run the generated
   suite against the real function (the *baseline*, which must pass) and against
   a set of :class:`Mutant` variants produced by an **injectable** mutant
   generator. A mutant is *killed* when at least one generated test fails on it.
   The **mutation score** is the fraction of mutants killed -- a good suite
   kills them all; a weak suite lets them survive, so the score discriminates
   suite quality. The mutant generator is injected (a plain callable returning
   :class:`Mutant` objects), so the whole flow is deterministic and needs no
   external tooling such as ``mutmut``.

The module depends only on the standard library and never imports from other
Thomas packages, so it is safe to use from the ``tools`` tier.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

__all__ = [
    "EDGE",
    "FAILURE",
    "FunctionSpec",
    "Requirement",
    "GeneratedTest",
    "GeneratedSuite",
    "Mutant",
    "MutantOutcome",
    "MutationReport",
    "GenerationError",
    "BaselineError",
    "SuiteResult",
    "generate_tests",
    "run_test",
    "run_suite",
    "mutation_test",
    "with_oracle",
]

# Test kinds.
EDGE = "edge"
FAILURE = "failure"
_VALID_KINDS = frozenset({EDGE, FAILURE})

# A test harness must run arbitrary caller-supplied functions and their mutated
# variants, so a mutant may raise almost anything. We deliberately enumerate a
# *specific* (non-broad) tuple of common exception families rather than catching
# ``Exception``: a raise that is not one of these is a genuine defect in the
# spec/harness and should surface, not be silently swallowed.
_CAUGHT_ERRORS: tuple[type[BaseException], ...] = (
    ArithmeticError,  # covers ZeroDivisionError, OverflowError, FloatingPointError
    AssertionError,
    AttributeError,
    BufferError,
    EOFError,
    LookupError,  # covers IndexError, KeyError
    MemoryError,
    NameError,  # covers UnboundLocalError
    ReferenceError,
    RuntimeError,  # covers RecursionError, NotImplementedError
    StopIteration,
    StopAsyncIteration,
    TypeError,
    UnicodeError,  # covers Unicode{Decode,Encode,Translate}Error
    ValueError,
)


class GenerationError(ValueError):
    """Raised when a requirement is inconsistent with the target function.

    Signals that generation cannot produce a trustworthy test: an ``edge``
    requirement whose input makes the correct function raise, an ``edge`` input
    where the function disagrees with the oracle, or a ``failure`` requirement
    whose input does not raise the declared exception on the correct function.
    """


class BaselineError(RuntimeError):
    """Raised when the generated suite does not pass against the real function.

    A mutation score is only meaningful once the suite passes on the correct
    implementation; otherwise a "killed" mutant cannot be distinguished from a
    broken test.
    """


@dataclass(frozen=True)
class FunctionSpec:
    """Declarative spec of the function under test.

    Attributes:
        name: Human-readable identifier used in reporting.
        func: The correct implementation -- the function under test.
        oracle: Optional independent reference used to *compute* expected values
            for edge cases. When omitted, ``func`` is its own oracle (a
            characterization-style spec); providing an independent oracle makes
            generation validate that ``func`` actually agrees with it.
    """

    name: str
    func: Callable[..., Any]
    oracle: Callable[..., Any] | None = None

    def expected_for(self, inputs: tuple[Any, ...]) -> Any:
        """Compute the expected output for ``inputs`` using the oracle."""
        reference = self.oracle if self.oracle is not None else self.func
        return reference(*inputs)


@dataclass(frozen=True)
class Requirement:
    """A single requirement linking a property to a concrete probe input.

    Attributes:
        id: Stable requirement identifier (e.g. ``"REQ-1"``). Must be non-empty;
            every generated test carries it.
        text: The property the requirement expresses (e.g. "rejects negative
            input").
        kind: Either :data:`EDGE` (boundary input that yields a value) or
            :data:`FAILURE` (invalid input that must raise).
        inputs: Positional arguments passed to the function under test.
        exception: For :data:`FAILURE` requirements, the exception type the
            function must raise. Ignored for :data:`EDGE` requirements.
    """

    id: str
    text: str
    kind: str
    inputs: tuple[Any, ...]
    exception: type[BaseException] = ValueError

    @classmethod
    def edge(cls, id: str, text: str, inputs: tuple[Any, ...]) -> Requirement:
        """Construct an edge (boundary) requirement."""
        return cls(id=id, text=text, kind=EDGE, inputs=tuple(inputs))

    @classmethod
    def failure(
        cls,
        id: str,
        text: str,
        inputs: tuple[Any, ...],
        exception: type[BaseException] = ValueError,
    ) -> Requirement:
        """Construct a failure requirement (input must raise ``exception``)."""
        return cls(id=id, text=text, kind=FAILURE, inputs=tuple(inputs), exception=exception)


@dataclass(frozen=True)
class GeneratedTest:
    """A concrete, requirement-linked test case.

    Attributes:
        requirement_id: The id of the requirement this test verifies (always
            populated).
        requirement_text: The property being verified, copied for traceability.
        kind: :data:`EDGE` or :data:`FAILURE`.
        inputs: Positional arguments to call the function with.
        expected: For :data:`EDGE`, the expected return value (computed from the
            oracle). For :data:`FAILURE`, the exception *type* expected to be
            raised.
    """

    requirement_id: str
    requirement_text: str
    kind: str
    inputs: tuple[Any, ...]
    expected: Any


@dataclass(frozen=True)
class GeneratedSuite:
    """An ordered collection of generated tests plus the originating spec."""

    spec: FunctionSpec
    tests: tuple[GeneratedTest, ...]

    def requirement_ids(self) -> tuple[str, ...]:
        """Requirement ids covered, in test order (may repeat)."""
        return tuple(test.requirement_id for test in self.tests)

    def kinds(self) -> frozenset[str]:
        """The set of test kinds present in the suite."""
        return frozenset(test.kind for test in self.tests)

    def of_kind(self, kind: str) -> tuple[GeneratedTest, ...]:
        """Return the tests of a given kind."""
        return tuple(test for test in self.tests if test.kind == kind)

    def __len__(self) -> int:
        return len(self.tests)


@dataclass(frozen=True)
class Mutant:
    """A perturbed variant of the function under test.

    Attributes:
        id: Stable mutant identifier (e.g. ``"flip-lt"`` or ``"off-by-one"``).
        description: What was perturbed, for reporting.
        func: The mutated callable. Must accept the same arguments as the
            function under test.
    """

    id: str
    description: str
    func: Callable[..., Any]


@dataclass(frozen=True)
class MutantOutcome:
    """The result of running the suite against one mutant.

    Attributes:
        mutant_id: The mutant's id.
        description: The mutant's description.
        killed: True when at least one test failed on the mutant.
        failing_requirement_ids: Requirement ids whose test detected the mutant
            (empty when the mutant survived).
    """

    mutant_id: str
    description: str
    killed: bool
    failing_requirement_ids: tuple[str, ...]


@dataclass(frozen=True)
class MutationReport:
    """Aggregate result of mutation-testing a generated suite.

    Attributes:
        total: Number of mutants evaluated.
        killed: Number of mutants killed (detected by the suite).
        outcomes: Per-mutant results, in generator order.
        baseline_passed: Always True in a returned report (the suite passed on
            the correct function); a failing baseline raises
            :class:`BaselineError` instead.
    """

    total: int
    killed: int
    outcomes: tuple[MutantOutcome, ...]
    baseline_passed: bool = True

    @property
    def score(self) -> float:
        """Mutation score: fraction of mutants killed, in ``[0.0, 1.0]``."""
        if self.total == 0:
            return 0.0
        return self.killed / self.total

    @property
    def survivors(self) -> tuple[str, ...]:
        """Ids of mutants that survived (were not detected)."""
        return tuple(o.mutant_id for o in self.outcomes if not o.killed)

    @property
    def killed_ids(self) -> tuple[str, ...]:
        """Ids of mutants that were killed."""
        return tuple(o.mutant_id for o in self.outcomes if o.killed)


# Type alias for the injectable mutant generator: a zero-argument callable that
# returns the mutants to validate against. Injecting it keeps mutation testing
# hermetic and deterministic (no source parsing, no external mutmut).
MutantGenerator = Callable[[], Sequence[Mutant]]


def _validate_requirement(req: Requirement) -> None:
    if not req.id or not str(req.id).strip():
        raise GenerationError("every requirement must have a non-empty id")
    if req.kind not in _VALID_KINDS:
        raise GenerationError(
            f"requirement {req.id!r} has invalid kind {req.kind!r}; expected one of {sorted(_VALID_KINDS)}"
        )


def _generate_edge_test(spec: FunctionSpec, req: Requirement) -> GeneratedTest:
    # Compute the expected value from the oracle.
    try:
        expected = spec.expected_for(req.inputs)
    except _CAUGHT_ERRORS as exc:
        raise GenerationError(
            f"edge requirement {req.id!r} oracle raised {type(exc).__name__} "
            f"on inputs {req.inputs!r}; an edge case must yield a value"
        ) from exc
    # Validate the correct function agrees with the oracle (no-op when func is
    # its own oracle, meaningful when an independent oracle was supplied).
    try:
        actual = spec.func(*req.inputs)
    except _CAUGHT_ERRORS as exc:
        raise GenerationError(
            f"edge requirement {req.id!r}: function {spec.name!r} raised "
            f"{type(exc).__name__} on edge inputs {req.inputs!r}"
        ) from exc
    if actual != expected:
        raise GenerationError(
            f"edge requirement {req.id!r}: function {spec.name!r} returned "
            f"{actual!r} but oracle expected {expected!r} for inputs {req.inputs!r}"
        )
    return GeneratedTest(
        requirement_id=req.id,
        requirement_text=req.text,
        kind=EDGE,
        inputs=req.inputs,
        expected=expected,
    )


def _generate_failure_test(spec: FunctionSpec, req: Requirement) -> GeneratedTest:
    # Confirm the correct function actually raises the declared exception.
    raised: BaseException | None = None
    try:
        spec.func(*req.inputs)
    except req.exception as exc:
        raised = exc
    except _CAUGHT_ERRORS as exc:
        raise GenerationError(
            f"failure requirement {req.id!r}: function {spec.name!r} raised "
            f"{type(exc).__name__} but requirement expects "
            f"{req.exception.__name__} for inputs {req.inputs!r}"
        ) from exc
    if raised is None:
        raise GenerationError(
            f"failure requirement {req.id!r}: function {spec.name!r} did not "
            f"raise {req.exception.__name__} for invalid inputs {req.inputs!r}"
        )
    return GeneratedTest(
        requirement_id=req.id,
        requirement_text=req.text,
        kind=FAILURE,
        inputs=req.inputs,
        expected=req.exception,
    )


def generate_tests(spec: FunctionSpec, requirements: Sequence[Requirement]) -> GeneratedSuite:
    """Generate a requirement-linked test suite from a spec and requirements.

    For each requirement, a single :class:`GeneratedTest` is produced that links
    back to the requirement id. ``edge`` requirements yield a test whose expected
    value is computed from the oracle; ``failure`` requirements yield a test that
    asserts the declared exception is raised. Generation validates that every
    requirement is self-consistent with the correct function, so the returned
    suite is guaranteed to pass against ``spec.func``.

    Args:
        spec: The function under test and its optional reference oracle.
        requirements: The requirements to cover. Must be non-empty and each must
            have a non-empty id.

    Returns:
        A :class:`GeneratedSuite`, with tests in requirement order (deterministic).

    Raises:
        GenerationError: If ``requirements`` is empty, a requirement has an empty
            id or invalid kind, or a requirement is inconsistent with ``spec.func``.
    """
    if not requirements:
        raise GenerationError("at least one requirement is required")

    tests: list[GeneratedTest] = []
    for req in requirements:
        _validate_requirement(req)
        if req.kind == EDGE:
            tests.append(_generate_edge_test(spec, req))
        else:
            tests.append(_generate_failure_test(spec, req))
    return GeneratedSuite(spec=spec, tests=tuple(tests))


def run_test(test: GeneratedTest, func: Callable[..., Any]) -> bool:
    """Run a single generated test against ``func`` and return whether it passed.

    An ``edge`` test passes when ``func(*inputs)`` returns a value equal to the
    expected value and does not raise. A ``failure`` test passes when
    ``func(*inputs)`` raises an exception that is an instance of the expected
    exception type. Any other outcome (wrong value, wrong/absent exception,
    unexpected raise) is a failure.
    """
    if test.kind == FAILURE:
        expected_exc = test.expected
        try:
            func(*test.inputs)
        except expected_exc:
            return True
        except _CAUGHT_ERRORS:
            # Raised, but the wrong exception type -> test fails.
            return False
        # No exception raised -> the invalid input was accepted -> test fails.
        return False

    # Edge case: must return the expected value without raising.
    try:
        result = func(*test.inputs)
    except _CAUGHT_ERRORS:
        return False
    return result == test.expected


@dataclass(frozen=True)
class SuiteResult:
    """Per-test results of running a suite against one function."""

    results: tuple[tuple[GeneratedTest, bool], ...] = field(default_factory=tuple)

    @property
    def all_passed(self) -> bool:
        """True when every test passed."""
        return all(passed for _, passed in self.results)

    @property
    def failing_requirement_ids(self) -> tuple[str, ...]:
        """Requirement ids whose test failed, in order (deduplicated)."""
        seen: dict[str, None] = {}
        for test, passed in self.results:
            if not passed:
                seen.setdefault(test.requirement_id, None)
        return tuple(seen)


def run_suite(suite: GeneratedSuite, func: Callable[..., Any]) -> SuiteResult:
    """Run every test in ``suite`` against ``func`` and collect per-test results."""
    results = tuple((test, run_test(test, func)) for test in suite.tests)
    return SuiteResult(results=results)


def mutation_test(
    suite: GeneratedSuite,
    mutant_generator: MutantGenerator,
    *,
    spec: FunctionSpec | None = None,
) -> MutationReport:
    """Validate a generated suite with mutation testing.

    First runs ``suite`` against the correct function (the baseline). If the
    baseline does not pass, a :class:`BaselineError` is raised -- a mutation
    score is meaningless when the suite fails on the correct implementation.
    Then runs the suite against each mutant from ``mutant_generator``; a mutant
    is *killed* when at least one test fails on it. The report's mutation score
    is ``killed / total``.

    Args:
        suite: The generated suite to validate.
        mutant_generator: A zero-argument callable returning the mutants to run
            against. Injecting it keeps the process hermetic and deterministic.
        spec: The spec whose ``func`` is the baseline. Defaults to ``suite.spec``.

    Returns:
        A :class:`MutationReport` with per-mutant outcomes and the score.

    Raises:
        BaselineError: If the suite does not fully pass on the correct function.
        ValueError: If the mutant generator yields no mutants.
    """
    baseline_spec = spec if spec is not None else suite.spec
    baseline = run_suite(suite, baseline_spec.func)
    if not baseline.all_passed:
        raise BaselineError(
            f"suite does not pass on the correct function {baseline_spec.name!r}; "
            f"failing requirements: {list(baseline.failing_requirement_ids)}"
        )

    mutants = tuple(mutant_generator())
    if not mutants:
        raise ValueError("mutant generator produced no mutants")

    outcomes: list[MutantOutcome] = []
    killed = 0
    for mutant in mutants:
        result = run_suite(suite, mutant.func)
        was_killed = not result.all_passed
        if was_killed:
            killed += 1
        outcomes.append(
            MutantOutcome(
                mutant_id=mutant.id,
                description=mutant.description,
                killed=was_killed,
                failing_requirement_ids=result.failing_requirement_ids,
            )
        )
    return MutationReport(
        total=len(mutants),
        killed=killed,
        outcomes=tuple(outcomes),
        baseline_passed=True,
    )


def with_oracle(spec: FunctionSpec, oracle: Callable[..., Any]) -> FunctionSpec:
    """Return a copy of ``spec`` with an independent reference ``oracle`` set."""
    return replace(spec, oracle=oracle)
