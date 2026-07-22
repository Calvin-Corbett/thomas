"""Tests for CAP-143 differential migration harness (thomas/tools/migration_harness.py).

Proves the exact Level-2 acceptance line: an equivalent candidate passes over
the corpus; a divergent candidate yields a counterexample and, with a converging
fix, reaches equivalence on retry; a persistently-divergent input is quarantined
and reported (not silently passed); the frozen equivalence suite is emitted; and
the whole thing is deterministic.

Everything is hermetic: two plain Python functions stand in for a legacy vs.
rewritten module, the fix step is a fake that converges, temp dirs come from
pytest's ``tmp_path``, and there is no network / clock / global state.
"""

from __future__ import annotations

import json

import pytest

from thomas.tools.migration_harness import (
    FixAttempt,
    MigrationHarness,
    Outcome,
    prove_migration,
    run_capture,
)


# --- stand-in "legacy" source implementation --------------------------------
def legacy_normalize(text: str) -> str:
    """Source of truth: trim, collapse inner whitespace, lowercase."""

    return " ".join(text.split()).lower()


# A deterministic corpus of inputs covering trimming, casing, and collapsing.
CORPUS = (
    "Hello World",
    "  MixedCase  ",
    "already fine",
    "TABS\tAND\nNEWLINES",
    "MULTIPLE     SPACES",
    "",
)


def _corpus_size() -> int:
    return len(CORPUS)


# --- acceptance 1: equivalent candidate passes over the corpus --------------
def test_equivalent_candidate_passes_over_corpus() -> None:
    def rewritten(text: str) -> str:
        # Independent reimplementation that is behaviourally identical.
        return " ".join(text.strip().split()).lower()

    report = prove_migration(legacy_normalize, rewritten, CORPUS)

    assert report.equivalent is True
    assert report.corpus_size == _corpus_size()
    assert len(report.passing_ids) == _corpus_size()
    assert report.quarantined == ()
    assert report.counterexamples == ()
    assert report.attempts_used == 0


# --- acceptance 2: divergent candidate -> counterexample, then converges ----
def test_divergence_yields_counterexample_and_converges_on_retry() -> None:
    # Broken rewrite: forgets to lowercase. Diverges on any cased input.
    def broken(text: str) -> str:
        return " ".join(text.split())

    # A fake fix step that *converges*: after one attempt it produces the
    # correct rewrite. It inspects the divergences to prove they are wired in.
    fix_calls: list[FixAttempt] = []

    def fix_step(attempt: FixAttempt):
        fix_calls.append(attempt)
        # The counterexamples must be real divergences on the corpus.
        assert attempt.divergences
        assert all(d.source.kind == "return" for d in attempt.divergences)

        def fixed(text: str) -> str:
            return " ".join(text.split()).lower()

        return fixed

    harness = MigrationHarness(max_retries=3)
    report = harness.run(legacy_normalize, broken, CORPUS, fix_step=fix_step)

    # A counterexample was recorded for the initial divergence.
    assert len(report.counterexamples) >= 1
    first = report.counterexamples[0]
    assert first.attempt == 0
    assert first.divergence.source.value != first.divergence.candidate.value
    assert first.divergence.input_id in first.diverging_ids

    # The converging fix reached equivalence on retry.
    assert report.equivalent is True
    assert report.attempts_used == 1
    assert report.quarantined == ()
    assert len(report.passing_ids) == _corpus_size()
    assert len(fix_calls) == 1


# --- acceptance 3: persistently-divergent input is quarantined, not passed ---
def test_persistent_divergence_is_quarantined_and_reported() -> None:
    poison = "POISON"
    corpus = ("Hello World", poison, "another")

    # Candidate is right for everything EXCEPT the poison case, which no fix
    # ever repairs.
    def make_candidate():
        def candidate(text: str) -> str:
            if text == poison:
                return "WRONG-ALWAYS"
            return " ".join(text.split()).lower()

        return candidate

    def fix_step(attempt: FixAttempt):
        # A "fix" that never actually repairs the poison case.
        return make_candidate()

    harness = MigrationHarness(max_retries=2)
    report = harness.run(legacy_normalize, make_candidate(), corpus, fix_step=fix_step)

    # Not equivalent, retries exhausted.
    assert report.equivalent is False
    assert report.attempts_used == 2

    # The poison input is quarantined as a first-class record -- NOT dropped and
    # NOT silently counted as passing.
    assert len(report.quarantined) == 1
    q = report.quarantined[0]
    assert q.case == poison
    assert q.source.value == "poison"
    assert q.candidate.value == "WRONG-ALWAYS"
    assert q.attempts == 2

    # It is reported in quarantined_ids and excluded from passing_ids.
    assert q.input_id in report.quarantined_ids
    assert q.input_id not in report.passing_ids
    # The other two inputs still pass.
    assert len(report.passing_ids) == 2

    # And it is reported via the summary surface, not swallowed.
    assert report.summary()["quarantined"] == [q.input_id]


# --- acceptance 3b: raising behaviour is compared, not just return values ----
def test_raise_vs_return_is_a_divergence() -> None:
    def source(x: int) -> int:
        if x == 0:
            raise ValueError("no zero")
        return 100 // x

    def candidate(x: int) -> int:
        # Returns 0 instead of raising on x == 0 -> behavioural divergence.
        if x == 0:
            return 0
        return 100 // x

    report = prove_migration(source, candidate, (1, 2, 0, 5))

    assert report.equivalent is False
    assert len(report.quarantined) == 1
    q = report.quarantined[0]
    assert q.case == 0
    assert q.source.kind == "raise"
    assert q.source.error == "ValueError: no zero"
    assert q.candidate.kind == "return"


# --- acceptance 4: frozen equivalence suite is emitted ----------------------
def test_frozen_equivalence_suite_is_emitted(tmp_path) -> None:
    def rewritten(text: str) -> str:
        return " ".join(text.split()).lower()

    report = prove_migration(legacy_normalize, rewritten, CORPUS)
    suite = report.frozen_suite

    # Suite = corpus + expected (source) outcomes.
    assert suite.size == _corpus_size()
    ids = [c.input_id for c in suite.cases]
    assert ids == sorted(ids)  # stable, ordered
    for c in suite.cases:
        assert c.expected == Outcome.returned(legacy_normalize(c.case))

    # It serialises to JSON and round-trips structurally.
    out = tmp_path / "suite" / "equivalence.json"
    written = suite.write_json(out)
    assert written.exists()
    doc = json.loads(written.read_text(encoding="utf-8"))
    assert doc["version"] == 1
    assert doc["size"] == _corpus_size()
    assert len(doc["cases"]) == _corpus_size()

    # The frozen suite verifies a good candidate and flags a bad one.
    assert suite.verify(rewritten) == ()

    def bad(text: str) -> str:
        return text  # no normalization

    failed = suite.verify(bad)
    assert len(failed) > 0


# --- acceptance 5: determinism ----------------------------------------------
def test_determinism_same_inputs_same_report() -> None:
    def broken(text: str) -> str:
        return " ".join(text.split())  # missing lowercase

    def fix_step(attempt: FixAttempt):
        def fixed(text: str) -> str:
            return " ".join(text.split()).lower()

        return fixed

    def run_once():
        harness = MigrationHarness(max_retries=3)
        return harness.run(legacy_normalize, broken, CORPUS, fix_step=fix_step)

    a = run_once()
    b = run_once()

    assert a.summary() == b.summary()
    assert a.frozen_suite.to_dict() == b.frozen_suite.to_dict()
    assert a.passing_ids == b.passing_ids
    assert [c.divergence.input_id for c in a.counterexamples] == [c.divergence.input_id for c in b.counterexamples]
    assert a.attempts_used == b.attempts_used


def test_run_capture_captures_return_and_raise() -> None:
    assert run_capture(lambda x: x + 1, 1) == Outcome.returned(2)

    def boom(_):
        raise KeyError("missing")

    out = run_capture(boom, None)
    assert out.kind == "raise"
    assert out.error == "KeyError: 'missing'"


def test_bound_hit_without_fix_step_records_counterexample() -> None:
    def broken(text: str) -> str:
        return text.upper()

    report = prove_migration(legacy_normalize, broken, ("Hi There",))

    assert report.equivalent is False
    assert report.attempts_used == 0
    assert len(report.counterexamples) == 1
    assert len(report.quarantined) == 1


def test_negative_max_retries_rejected() -> None:
    with pytest.raises(Exception):
        MigrationHarness(max_retries=-1)
