"""Tests for requirement-linked test generation with mutation validation.

Proves the acceptance line for CAP-087:
    "Generate requirement-linked edge and failure tests and validate them with
    mutation testing."

Every assertion is hermetic: the function under test and all mutants are plain
in-process callables defined here, the mutant generator is injected, no clock,
no network, no external tooling.
"""

from __future__ import annotations

import pytest

from thomas.tools.test_generation import (
    EDGE,
    FAILURE,
    BaselineError,
    FunctionSpec,
    GeneratedTest,
    GenerationError,
    Mutant,
    Requirement,
    generate_tests,
    mutation_test,
    run_suite,
    run_test,
    with_oracle,
)

# --------------------------------------------------------------------------- #
# Function under test: take(items, n) -> first n items; negative n is invalid. #
# --------------------------------------------------------------------------- #


def take(items, n):
    """Return the first ``n`` items; a negative ``n`` is invalid."""
    if n < 0:
        raise ValueError("n must be non-negative")
    return list(items[:n])


def _spec() -> FunctionSpec:
    return FunctionSpec(name="take", func=take)


def _requirements() -> list[Requirement]:
    # Edge cases cover the three named boundaries: 0, empty, and max.
    return [
        Requirement.edge("REQ-1", "n=0 yields an empty result", ([10, 20, 30], 0)),
        Requirement.edge("REQ-2", "empty input yields empty result", ([], 3)),
        Requirement.edge("REQ-3", "n equal to length yields all", ([10, 20, 30], 3)),
        Requirement.failure("REQ-4", "negative n is rejected", ([10, 20, 30], -1), ValueError),
    ]


def _strong_suite():
    return generate_tests(_spec(), _requirements())


# --------------------------------------------------------------------------- #
# Mutants (comparison-flip and off-by-one perturbations of ``take``).         #
# --------------------------------------------------------------------------- #


def _flip_guard_le(items, n):  # comparison flip: n < 0 -> n <= 0
    if n <= 0:
        raise ValueError("n must be non-negative")
    return list(items[:n])


def _flip_guard_gt(items, n):  # comparison flip: n < 0 -> n > 0
    if n > 0:
        raise ValueError("n must be non-negative")
    return list(items[:n])


def _slice_plus_one(items, n):  # off-by-one: items[:n] -> items[:n + 1]
    if n < 0:
        raise ValueError("n must be non-negative")
    return list(items[: n + 1])


def _slice_minus_one(items, n):  # off-by-one: items[:n] -> items[:n - 1]
    if n < 0:
        raise ValueError("n must be non-negative")
    return list(items[: n - 1])


def _guard_off_by_one(items, n):  # off-by-one on the guard boundary: n < 0 -> n < -1
    if n < -1:
        raise ValueError("n must be non-negative")
    return list(items[:n])


def _comparison_and_offbyone_mutants() -> list[Mutant]:
    return [
        Mutant("flip-le", "flip guard < to <=", _flip_guard_le),
        Mutant("flip-gt", "flip guard < to >", _flip_guard_gt),
        Mutant("slice+1", "off-by-one slice n+1", _slice_plus_one),
        Mutant("slice-1", "off-by-one slice n-1", _slice_minus_one),
        Mutant("guard-obo", "off-by-one guard boundary", _guard_off_by_one),
    ]


# --------------------------------------------------------------------------- #
# 1. Generated tests are requirement-linked and include edge + failure kinds. #
# --------------------------------------------------------------------------- #


def test_generated_tests_are_requirement_linked_edge_and_failure():
    suite = _strong_suite()

    # Every generated test names a requirement id (never empty).
    assert len(suite) == 4
    for test in suite.tests:
        assert isinstance(test, GeneratedTest)
        assert test.requirement_id
        assert test.requirement_id.strip()

    # The linkage matches the input requirement ids, in order.
    assert suite.requirement_ids() == ("REQ-1", "REQ-2", "REQ-3", "REQ-4")

    # Both edge and failure kinds are present.
    assert suite.kinds() == frozenset({EDGE, FAILURE})
    assert len(suite.of_kind(EDGE)) == 3
    assert len(suite.of_kind(FAILURE)) == 1

    # Failure expected is the exception type.
    assert suite.of_kind(FAILURE)[0].expected is ValueError


def test_edge_expected_values_are_computed_from_oracle():
    suite = _strong_suite()
    by_req = {t.requirement_id: t for t in suite.tests}
    assert by_req["REQ-1"].expected == []  # n=0 -> []
    assert by_req["REQ-2"].expected == []  # empty items -> []
    assert by_req["REQ-3"].expected == [10, 20, 30]  # n == len -> all


# --------------------------------------------------------------------------- #
# 2. The generated suite passes against the correct function.                 #
# --------------------------------------------------------------------------- #


def test_generated_suite_passes_on_correct_function():
    suite = _strong_suite()
    result = run_suite(suite, take)
    assert result.all_passed
    assert result.failing_requirement_ids == ()


# --------------------------------------------------------------------------- #
# 3. The suite kills comparison-flip and off-by-one mutants (high score).     #
# --------------------------------------------------------------------------- #


def test_suite_kills_all_comparison_flip_and_off_by_one_mutants():
    suite = _strong_suite()
    report = mutation_test(suite, _comparison_and_offbyone_mutants)

    assert report.baseline_passed is True
    assert report.total == 5
    assert report.killed == 5
    assert report.score == 1.0
    assert report.survivors == ()

    # Specifically: every comparison-flip and every off-by-one mutant is killed.
    killed = set(report.killed_ids)
    assert {"flip-le", "flip-gt"} <= killed  # comparison flips
    assert {"slice+1", "slice-1", "guard-obo"} <= killed  # off-by-one mutations

    # Each killed mutant reports which requirement detected it.
    for outcome in report.outcomes:
        assert outcome.killed
        assert outcome.failing_requirement_ids  # non-empty


# --------------------------------------------------------------------------- #
# 4. A deliberately weak suite yields a LOW score (metric discriminates).     #
# --------------------------------------------------------------------------- #


def _localized_mutants() -> list[Mutant]:
    # Both mutants differ from the correct function ONLY at a boundary:
    #   flip-le  differs only at n == 0
    #   guard-obo differs only at n == -1
    return [
        Mutant("flip-le", "flip guard < to <=", _flip_guard_le),
        Mutant("guard-obo", "off-by-one guard boundary", _guard_off_by_one),
    ]


def test_weak_suite_scores_lower_than_strong_suite():
    spec = _spec()

    # Weak suite: a single interior probe (n=1) that touches no boundary.
    weak = generate_tests(spec, [Requirement.edge("REQ-W", "interior sample", ([10, 20, 30], 1))])
    # Strong suite touches both boundaries the localized mutants live at.
    strong = _strong_suite()

    weak_report = mutation_test(weak, _localized_mutants)
    strong_report = mutation_test(strong, _localized_mutants)

    # Both suites pass their baseline on the correct function.
    assert weak_report.baseline_passed and strong_report.baseline_passed

    # Strong kills every mutant; weak kills none -> the score discriminates.
    assert strong_report.score == 1.0
    assert weak_report.score == 0.0
    assert weak_report.score < strong_report.score
    assert set(weak_report.survivors) == {"flip-le", "guard-obo"}


# --------------------------------------------------------------------------- #
# 5. Determinism: identical inputs produce identical reports.                 #
# --------------------------------------------------------------------------- #


def test_generation_and_mutation_are_deterministic():
    suite_a = _strong_suite()
    suite_b = _strong_suite()
    assert suite_a == suite_b

    report_a = mutation_test(suite_a, _comparison_and_offbyone_mutants)
    report_b = mutation_test(suite_b, _comparison_and_offbyone_mutants)

    assert report_a == report_b
    assert report_a.score == report_b.score
    assert report_a.killed_ids == report_b.killed_ids
    assert report_a.survivors == report_b.survivors


# --------------------------------------------------------------------------- #
# 6. run_test semantics for edge and failure kinds.                           #
# --------------------------------------------------------------------------- #


def test_run_test_edge_and_failure_semantics():
    suite = _strong_suite()
    by_req = {t.requirement_id: t for t in suite.tests}

    edge = by_req["REQ-1"]  # expects []
    failure = by_req["REQ-4"]  # expects ValueError

    # Edge passes on correct return, fails on wrong value and on unexpected raise.
    assert run_test(edge, take) is True
    assert run_test(edge, lambda items, n: [999]) is False
    assert run_test(edge, _flip_guard_le) is False  # raises where it should return

    # Failure passes when the right exception is raised, fails when none/other.
    assert run_test(failure, take) is True
    assert run_test(failure, lambda items, n: []) is False  # no raise
    assert run_test(failure, _raises_type_error) is False  # wrong exception type


def _raises_type_error(items, n):
    raise TypeError("wrong kind")


# --------------------------------------------------------------------------- #
# 7. Generation validates spec/requirement consistency.                       #
# --------------------------------------------------------------------------- #


def test_generation_rejects_empty_requirements():
    with pytest.raises(GenerationError):
        generate_tests(_spec(), [])


def test_generation_rejects_empty_requirement_id():
    with pytest.raises(GenerationError):
        generate_tests(_spec(), [Requirement.edge("", "no id", ([1], 0))])


def test_generation_rejects_invalid_kind():
    bad = Requirement(id="REQ-X", text="bad kind", kind="weird", inputs=([1], 0))
    with pytest.raises(GenerationError):
        generate_tests(_spec(), [bad])


def test_generation_rejects_edge_where_function_disagrees_with_oracle():
    # Independent oracle says take([1,2,3], 2) should be [1, 2, 3]; func says [1, 2].
    spec = with_oracle(_spec(), oracle=lambda items, n: list(items))
    with pytest.raises(GenerationError):
        generate_tests(spec, [Requirement.edge("REQ-E", "mismatch", ([1, 2, 3], 2))])


def test_generation_rejects_failure_that_does_not_raise():
    # n=2 is valid, so a failure requirement on it is inconsistent.
    with pytest.raises(GenerationError):
        generate_tests(_spec(), [Requirement.failure("REQ-F", "should raise", ([1, 2, 3], 2))])


# --------------------------------------------------------------------------- #
# 8. mutation_test guards: baseline must pass, generator must yield mutants.   #
# --------------------------------------------------------------------------- #


def test_mutation_test_raises_when_baseline_fails():
    suite = _strong_suite()
    # Point the baseline at a wrong "correct" function that fails the suite.
    wrong = FunctionSpec(name="wrong", func=_flip_guard_le)
    with pytest.raises(BaselineError):
        mutation_test(suite, _comparison_and_offbyone_mutants, spec=wrong)


def test_mutation_test_raises_on_empty_mutant_generator():
    suite = _strong_suite()
    with pytest.raises(ValueError):
        mutation_test(suite, lambda: [])
