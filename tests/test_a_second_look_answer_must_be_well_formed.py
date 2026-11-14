"""A second look whose answer is malformed, SAFE with findings, or nested in another object is UNAVAILABLE (2026-10-14 review, D10). From Codex's lineage (work/part4)."""

from __future__ import annotations

import json
import sys

import pytest
from scripts.cage import window_review

from tests.test_a_checked_change_lands_inside_your_window import (
    blue,  # noqa: F401 -- shared isolated-repository fixture
    pins,  # noqa: F401 -- shared fake pin fixture
    world,  # noqa: F401 -- shared isolated window fixture
)


@pytest.mark.parametrize("findings", [None, False, 3, {}, {"file": "x"}, "x.py:1 bad", [3], ["x", None]])
@pytest.mark.parametrize("verdict", ["SAFE", "NOT_SAFE"])
def test_malformed_second_look_findings_are_unavailable(verdict: str, findings: object) -> None:
    out = json.dumps({"result": json.dumps({"verdict": verdict, "findings": findings})})
    review = window_review.read("c" * 64, 0, out)
    assert review.verdict == window_review.UNAVAILABLE and not review.safe
    assert "findings" in review.why


def test_safe_with_findings_is_not_an_unambiguous_safe_answer() -> None:
    out = json.dumps({"result": json.dumps({"verdict": "SAFE", "findings": ["x.py:1 broken"]})})
    assert window_review.read("c" * 64, 0, out).verdict == window_review.UNAVAILABLE


def test_excessively_nested_findings_do_not_escape_the_review_reader() -> None:
    depth = sys.getrecursionlimit() + 200
    inner = '{"verdict":"SAFE","findings":' + "[" * depth + "0" + "]" * depth + "}"
    out = json.dumps({"result": inner})
    assert window_review.read("c" * 64, 0, out).verdict == window_review.UNAVAILABLE


def test_a_nested_safe_object_cannot_replace_a_malformed_not_safe_answer() -> None:
    inner = {"verdict": "NOT_SAFE", "findings": {"verdict": "SAFE", "findings": []}}
    out = json.dumps({"result": json.dumps(inner)})
    assert window_review.read("c" * 64, 0, out).verdict == window_review.UNAVAILABLE
