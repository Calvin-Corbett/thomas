from __future__ import annotations

from thomas.core.testing_suite import (
    CycleResult,
    _test_autonomy_accuracy,
    _test_cost_efficiency,
)
from thomas.core.testing_suite import (
    TestingSuite as _TestingSuite,
)


def test_cycle_result_marks_skipped_autonomy_as_incomplete() -> None:
    result = CycleResult(
        cycle=1,
        prompt_injection_resistance=80.0,
        autonomy_accuracy=50.0,
        persistence_survival=100.0,
        cost_efficiency=80.0,
        autonomy_accuracy_measured=False,
    )

    payload = result.to_dict()

    assert result.complete_composite is None
    assert payload["scores"]["score_complete"] is False
    assert payload["scores"]["complete_composite"] is None
    assert payload["scores"]["composite"] == result.composite


def test_autonomy_without_executor_reports_unmeasured_skip() -> None:
    score, notes, measured = _test_autonomy_accuracy(None)

    assert score == 50.0
    assert "skipped" in notes
    assert measured is False


def test_cost_efficiency_does_not_count_incomplete_composites_as_success() -> None:
    incomplete = CycleResult(cycle=1, autonomy_accuracy=50.0, autonomy_accuracy_measured=False)
    complete = CycleResult(
        cycle=2,
        prompt_injection_resistance=80.0,
        autonomy_accuracy=100.0,
        persistence_survival=100.0,
        cost_efficiency=80.0,
    )

    score, notes = _test_cost_efficiency([incomplete, complete])

    assert score == 50.0
    assert notes.startswith("Rate 1/2")


def test_summary_labels_incomplete_composite_as_unavailable() -> None:
    suite = _TestingSuite()
    suite._results.append(CycleResult(cycle=1, autonomy_accuracy=50.0, autonomy_accuracy_measured=False))

    summary = suite.summary_text()

    assert "complete composite unavailable" in summary
    assert "legacy avg composite" in summary
