from __future__ import annotations

from thomas.server.chat_delegation_canvas_review import review_canvas_html


def _canvas(body: str, *, styles: str = "", script: str = "") -> str:
    return (
        "<!doctype html>"
        f"<style>{styles}</style>"
        '<div id="tc-stage" data-reveal="pending">'
        f'<div class="el" style="--i:0">{body}</div>'
        "</div>"
        f"<script>{script}</script>"
    )


def test_review_returns_structural_presentation_evidence() -> None:
    evidence = review_canvas_html("any request wording", _canvas("Visible result <svg><rect></rect></svg>"))

    assert evidence.passed
    payload = evidence.to_dict()
    assert payload["review_version"] == "canvas-structural-v3"
    assert {check["check_id"] for check in payload["checks"]} >= {
        "render_contract",
        "document_parse",
        "visible_content",
        "content_mutation",
        "content_animation",
    }


def test_prompt_words_do_not_change_canvas_acceptance() -> None:
    html = _canvas("The frontier model's finished visual <svg><circle></circle></svg>")
    graph = review_canvas_html("make me a graph", html)
    game = review_canvas_html("make me a game", html)

    assert graph.passed == game.passed
    assert [check.check_id for check in graph.checks] == [check.check_id for check in game.checks]


def test_review_rejects_empty_contract_shell() -> None:
    evidence = review_canvas_html("ignored", '<div id="tc-stage" data-reveal="pending" style="--i:0"></div>')

    assert "visible_content_missing" in {issue.code for issue in evidence.issues}


def test_review_rejects_script_that_removes_stable_content() -> None:
    html = _canvas(
        '<div id="result">Stable result</div>',
        script='document.getElementById("result").remove()',
    )

    assert "content_mutation" in {issue.code for issue in review_canvas_html("ignored", html).issues}


def test_review_allows_transient_and_interactive_mutation() -> None:
    html = _canvas(
        '<div id="tip" class="tooltip">Hint</div><button id="button">Play</button><svg><rect></rect></svg>',
        script='document.getElementById("tip").remove();document.getElementById("button").remove()',
    )

    assert review_canvas_html("ignored", html).passed


def test_review_accepts_canonical_deterministic_canvas_renderer() -> None:
    from thomas.server.chat_delegation_canvas import build_canvas_html

    spec = """
    {
      "stage": {"w": 720, "h": 520, "bg": "#ffffff"},
      "elements": [
        {"id":"title","kind":"text","label":"Quarterly Revenue","geometry":{"x":80,"y":50},"motion":"rise-fade"},
        {"id":"q1","kind":"number","value":120,"geometry":{"x":160,"y":100},"motion":"count-up"}
      ],
      "sequence":{"order":["title","q1"],"stagger_ms":70}
    }
    """

    assert review_canvas_html("ignored", build_canvas_html(spec)).passed
