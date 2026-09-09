"""A typo in the request must not throw away a good render."""

from __future__ import annotations

import pytest

from thomas.server import chat_delegation_canvas_worker as worker
from thomas.server.chat_delegation_canvas_review import CanvasReviewIssue


def _issues(*codes: str) -> list[CanvasReviewIssue]:
    return [CanvasReviewIssue(code, f"{code} message") for code in codes]


def _blocking(issues: list[CanvasReviewIssue]) -> list[CanvasReviewIssue]:
    """The worker's rule, expressed once so the test pins the intent."""
    return [issue for issue in issues if issue.code != "subject_mismatch"]


def test_a_subject_mismatch_alone_does_not_discard_the_render() -> None:
    """The failure this fixes.

    "make me a graph pofmrvenue from am deup company" built a clean revenue
    chart, failed review, was repaired, built a clean chart again, and both were
    discarded -- because "pofmrvenue" cannot appear in any correct render. The
    user got "Canvas generation failed" for a typo.
    """
    assert _blocking(_issues("subject_mismatch")) == []


def test_an_objective_defect_still_stops_delivery() -> None:
    """Everything else is a property of the render itself, not a guess about
    wording, and must still block."""
    for code in (
        "contract_incomplete",
        "document_parse_failed",
        "visible_content_missing",
        "generic_placeholder",
        "chart_values_missing",
        "chart_label_value_mismatch",
    ):
        assert [i.code for i in _blocking(_issues(code))] == [code]


def test_a_subject_mismatch_beside_a_real_defect_still_blocks() -> None:
    """The concession is narrow: it only applies when nothing else is wrong."""
    blocking = _blocking(_issues("subject_mismatch", "chart_label_value_mismatch"))

    assert [i.code for i in blocking] == ["chart_label_value_mismatch"]


def test_the_worker_uses_exactly_this_rule() -> None:
    """Guards against the source drifting away from what this file asserts."""
    import inspect

    source = inspect.getsource(worker.run_canvas_worker)

    assert 'issue.code != "subject_mismatch"' in source
    assert "if blocking:" in source


@pytest.mark.parametrize("codes", [(), ("subject_mismatch",)])
def test_nothing_blocking_means_the_render_is_delivered(codes: tuple[str, ...]) -> None:
    assert _blocking(_issues(*codes)) == []
