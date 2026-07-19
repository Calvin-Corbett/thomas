from __future__ import annotations

from thomas.server.chat_delegation_canvas import (
    canvas_add_element,
    canvas_set_html,
    canvas_set_review,
    canvas_set_shell,
    canvas_start,
)
from thomas.server.chat_delegation_session import _normalize_record


def _record(*, state: str = "executing", proof_status: str = "missing") -> dict:
    return {
        "execution_id": "exec-partial-canvas",
        "state": state,
        "proof_status": proof_status,
        "proof": {"status": proof_status, "artifacts": []},
        "runtime_profile": {"canvas": True},
    }


def test_partial_construction_streams_without_unreviewed_final_html() -> None:
    canvas_start("exec-partial-canvas", "Quarterly Revenue")
    canvas_set_shell("exec-partial-canvas", {"w": 720, "h": 520, "bg": "#fff"})
    canvas_add_element("exec-partial-canvas", "div", '<div class="el">Q1</div>')
    canvas_set_html("exec-partial-canvas", "<!doctype html><p>unreviewed final</p>")

    normalized = _normalize_record(_record())

    assert normalized["canvas_status"] == "streaming"
    assert normalized["canvas_mode"] == "construct"
    assert 'id="tc-stage"' in normalized["canvas_shell"]
    assert normalized["canvas_elements"] == [{"layer": "div", "html": '<div class="el">Q1</div>'}]
    assert normalized["canvas_html"] == ""


def test_failed_review_withdraws_unreviewed_partial_construction() -> None:
    canvas_start("exec-partial-canvas", "Quarterly Revenue")
    canvas_set_shell("exec-partial-canvas", {"w": 720, "h": 520, "bg": "#fff"})
    canvas_add_element("exec-partial-canvas", "div", '<div class="el">Q1</div>')
    canvas_set_review(
        "exec-partial-canvas",
        {"status": "failed", "issues": [{"code": "semantic", "message": "labels swapped"}]},
    )

    normalized = _normalize_record(_record())

    assert normalized["canvas_review_status"] == "failed"
    assert normalized["canvas_shell"] == ""
    assert normalized["canvas_elements"] == []
    assert normalized["canvas_html"] == ""
