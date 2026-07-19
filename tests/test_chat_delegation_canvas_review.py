from __future__ import annotations

import pytest

from thomas.server.chat_delegation_canvas_review import (
    canvas_review_issues,
    review_canvas_html,
)
from thomas.server.chat_delegation_canvas_review_rules import chart_prompt_pairs


def _canvas(body: str, *, styles: str = "", script: str = "") -> str:
    return (
        "<!doctype html>"
        f"<style>{styles}</style>"
        '<div id="tc-stage" data-reveal="pending">'
        f'<div class="el" style="--i:0">{body}</div>'
        "</div>"
        f"<script>{script}</script>"
    )


def _issue_codes(prompt: str, html: str) -> set[str]:
    return {issue.code for issue in review_canvas_html(prompt, html).issues}


def test_review_returns_structured_presentation_evidence() -> None:
    evidence = review_canvas_html(
        "Create a quarterly revenue chart showing Q1 120 and Q2 135",
        _canvas("Quarterly Revenue Q1 120 Q2 135 <svg><rect></rect></svg>"),
    )

    assert evidence.passed
    payload = evidence.to_dict()
    assert payload["status"] == "passed"
    assert len(payload["source_sha256"]) == 64
    assert payload["review_version"] == "canvas-semantic-v2"
    assert {check["check_id"] for check in payload["checks"]} >= {
        "render_contract",
        "generic_placeholder",
        "requested_values",
        "requested_subject",
    }


def test_review_rejects_generic_task_board_substitution() -> None:
    html = _canvas(
        "<h1>Tasks - Separated Individually</h1>"
        "<div>Task 1 - Separate individual item</div>"
        "<div>Task 2 - Separate individual item</div>"
    )

    evidence = review_canvas_html("Create a Trey game, chart, and recipe", html)

    assert "generic_placeholder" in {issue.code for issue in evidence.issues}
    assert "render is a generic task placeholder" in canvas_review_issues("Create a Trey game, chart, and recipe", html)


def test_review_rejects_empty_contract_shell_and_semantic_mismatch() -> None:
    empty_shell = (
        '<!doctype html><style>.noise{content:"Q1 Q2 Quarterly Revenue"}</style>'
        '<div id="tc-stage" data-reveal="pending"></div>'
        '<script>document.querySelector("#tc-stage").dataset.reveal="play";'
        "requestAnimationFrame(()=>{});setTimeout(()=>{},2500)</script>"
    )
    empty_issues = canvas_review_issues("Draw Q1 and Q2 revenue", empty_shell)
    assert "render has too little visible content" in empty_issues
    assert any("missing requested data labels" in issue for issue in empty_issues)

    mismatch_issues = canvas_review_issues(
        "Draw Q1 Q2 quarterly revenue",
        _canvas("Fruit Sales Apples 40 Bananas 60 <svg><rect></rect></svg>"),
    )
    assert any("missing requested data labels" in issue for issue in mismatch_issues)
    assert "render does not match the requested subject" in mismatch_issues


@pytest.mark.parametrize(
    "styles,hidden_markup",
    [
        ("", "<div hidden>Quarterly Revenue Q1 120 Q2 135</div>"),
        ("", '<div style="display:none">Quarterly Revenue Q1 120 Q2 135</div>'),
        (
            ".wrapper .secret{visibility:hidden}",
            '<div class="wrapper"><div class="secret">Quarterly Revenue Q1 120 Q2 135</div></div>',
        ),
        (".el > .secret{opacity:0}", '<div class="secret">Quarterly Revenue Q1 120 Q2 135</div>'),
        ("[data-secret]{display:none}", "<div data-secret>Quarterly Revenue Q1 120 Q2 135</div>"),
        (".secret:not(.shown){display:none}", '<div class="secret">Quarterly Revenue Q1 120 Q2 135</div>'),
        (
            ".marker + .secret{display:none}",
            '<div class="marker"></div><div class="secret">Quarterly Revenue Q1 120 Q2 135</div>',
        ),
        (
            ".marker ~ .secret{display:none}",
            '<div class="marker"></div><span></span><div class="secret">Quarterly Revenue Q1 120 Q2 135</div>',
        ),
        ("", '<div style="position:absolute;left:-99999px">Quarterly Revenue Q1 120 Q2 135</div>'),
        ("", '<div style="position:absolute;inset:-99999px">Quarterly Revenue Q1 120 Q2 135</div>'),
        ("", '<div style="clip-path:inset(100%)">Quarterly Revenue Q1 120 Q2 135</div>'),
        ("", '<div style="clip-path:circle(0)">Quarterly Revenue Q1 120 Q2 135</div>'),
        ("", '<div style="height:0;width:0;overflow:hidden">Quarterly Revenue Q1 120 Q2 135</div>'),
        ("", '<div style="color:transparent">Quarterly Revenue Q1 120 Q2 135</div>'),
        ("", '<div style="color:white;background:white">Quarterly Revenue Q1 120 Q2 135</div>'),
        ("", '<div style="background:#ffffff;color:#fff">Quarterly Revenue Q1 120 Q2 135</div>'),
        ("", '<div style="width:1px;height:1px;overflow:hidden">Quarterly Revenue Q1 120 Q2 135</div>'),
        ("", '<div style="font-size:0">Quarterly Revenue Q1 120 Q2 135</div>'),
        ("", '<div style="position:fixed;top:500vh">Quarterly Revenue Q1 120 Q2 135</div>'),
        ("", '<div style="position:absolute;left:-200vw">Quarterly Revenue Q1 120 Q2 135</div>'),
        ("", '<div style="transform:scale(0)">Quarterly Revenue Q1 120 Q2 135</div>'),
        ("", '<div style="transform:translateX(-200vw)">Quarterly Revenue Q1 120 Q2 135</div>'),
        ("", '<div style="filter:opacity(0)">Quarterly Revenue Q1 120 Q2 135</div>'),
        ("", '<div style="content-visibility:hidden">Quarterly Revenue Q1 120 Q2 135</div>'),
        (
            "",
            '<div style="position:absolute;width:1px;height:1px;margin:-1px;overflow:hidden;'
            'clip:rect(0, 0, 0, 0);white-space:nowrap">Quarterly Revenue Q1 120 Q2 135</div>',
        ),
        (".el > .wrapper{display:none}", '<div class="wrapper">Quarterly Revenue Q1 120 Q2 135</div>'),
        (".secret:first-child{display:none}", '<div><div class="secret">Quarterly Revenue Q1 120 Q2 135</div></div>'),
        (".secret{--alpha:0;opacity:var(--alpha)}", '<div class="secret">Quarterly Revenue Q1 120 Q2 135</div>'),
        (":root{--alpha:0}.secret{opacity:var(--alpha)}", '<div class="secret">Quarterly Revenue Q1 120 Q2 135</div>'),
        (".secret{opacity:calc(1 - 1)}", '<div class="secret">Quarterly Revenue Q1 120 Q2 135</div>'),
        (
            ".secret{--shown:1;opacity:calc(var(--shown) - 1)}",
            '<div class="secret">Quarterly Revenue Q1 120 Q2 135</div>',
        ),
    ],
)
def test_review_rejects_hidden_or_offscreen_requested_evidence(styles: str, hidden_markup: str) -> None:
    html = _canvas(f"Fruit summary 42 {hidden_markup}", styles=styles)

    codes = _issue_codes("Create a quarterly revenue chart showing Q1 120 and Q2 135", html)

    assert "requested_values_missing" in codes
    assert "subject_mismatch" in codes


@pytest.mark.parametrize(
    "styles,body,script",
    [
        ("", '<div id="secret">Quarterly Revenue Q1 120 Q2 135</div>', 'document.getElementById("secret").remove()'),
        (
            "",
            '<div id="secret">Quarterly Revenue Q1 120 Q2 135</div>',
            'const item=document.getElementById("secret");item.hidden=true',
        ),
        (
            "",
            '<div id="secret">Quarterly Revenue Q1 120 Q2 135</div>',
            'document.getElementById("secret").style.display="none"',
        ),
        (
            "",
            '<div id="secret">Quarterly Revenue Q1 120 Q2 135</div>',
            'document.getElementById("secret").setAttribute("aria-hidden","true")',
        ),
        (
            "",
            '<div id="secret">Quarterly Revenue Q1 120 Q2 135</div>',
            'document.getElementById("secret").innerHTML=""',
        ),
        (
            "",
            '<div class="secret">Quarterly Revenue Q1 120 Q2 135</div>',
            'document.querySelectorAll(".secret").forEach(item=>item.remove())',
        ),
        (
            ".conceal{display:none}",
            '<div id="secret">Quarterly Revenue Q1 120 Q2 135</div>',
            'document.getElementById("secret").classList.add("conceal")',
        ),
        (
            "",
            '<div id="secret">Quarterly Revenue Q1 120 Q2 135</div>',
            'Object.assign(document.getElementById("secret").style,{display:"none"})',
        ),
        (
            "",
            '<div id="secret">Quarterly Revenue Q1 120 Q2 135</div>',
            'document.getElementById("secret").setAttribute("hidden","")',
        ),
        (
            "",
            '<div id="secret">Quarterly Revenue Q1 120 Q2 135</div>',
            'document.getElementById("secret").style.setProperty("display","none")',
        ),
        (
            ".conceal{display:none}",
            '<div id="secret">Quarterly Revenue Q1 120 Q2 135</div>',
            'document.getElementById("secret").className="conceal"',
        ),
        (
            "",
            '<div id="secret">Quarterly Revenue Q1 120 Q2 135</div>',
            'document.getElementById("secret").style.cssText="display:none"',
        ),
        ("", '<div id="secret">Quarterly Revenue Q1 120 Q2 135</div>', "secret.hidden=true"),
        ("", '<div id="secret">Quarterly Revenue Q1 120 Q2 135</div>', 'secret.textContent=""'),
        ("", "<div>Quarterly Revenue Q1 120 Q2 135</div>", "document.body.replaceChildren()"),
    ],
)
def test_review_rejects_suspicious_requested_content_removal(styles: str, body: str, script: str) -> None:
    evidence = review_canvas_html(
        "Create a quarterly revenue chart showing Q1 120 and Q2 135",
        _canvas(body, styles=styles, script=script),
    )

    issue = next(issue for issue in evidence.issues if issue.code == "requested_content_mutation")
    assert issue.details["findings"]


def test_review_rejects_animation_that_finishes_with_requested_content_hidden() -> None:
    html = _canvas(
        '<div class="secret">Quarterly Revenue Q1 120 Q2 135</div>',
        styles="@keyframes vanish{to{opacity:0}} .secret{animation:vanish .01s forwards}",
    )

    assert "requested_content_disappears" in _issue_codes(
        "Create a quarterly revenue chart showing Q1 120 and Q2 135", html
    )


def test_review_requires_stable_chart_labels_and_values() -> None:
    evidence = review_canvas_html(
        "Create a quarterly revenue chart showing Q1 120 and Q2 135",
        _canvas("Quarterly Revenue <svg><rect></rect></svg>"),
    )

    codes = {issue.code for issue in evidence.issues}
    assert "requested_values_missing" in codes
    assert "chart_values_missing" in codes


def test_review_rejects_swapped_chart_label_value_semantics() -> None:
    evidence = review_canvas_html(
        "Create a quarterly revenue chart showing Q1 120 and Q2 135",
        _canvas("Quarterly Revenue Q1 135 Q2 120 <svg><rect></rect></svg>"),
    )

    issue = next(issue for issue in evidence.issues if issue.code == "chart_label_value_mismatch")
    assert {row["label"] for row in issue.details["mismatches"]} == {"q1", "q2"}


def test_review_does_not_parse_title_markers_as_chart_label_value_pairs() -> None:
    prompt = "Create a bar chart titled DATA-CHART-MARKER-56 showing Alpha 3, Beta 7, and Gamma 5. Show TOTAL 15."

    assert ("data-chart-marker-5", "6") not in chart_prompt_pairs(prompt)
    assert review_canvas_html(
        prompt,
        _canvas("DATA-CHART-MARKER-56 Alpha 3 Beta 7 Gamma 5 TOTAL 15 <svg><rect></rect></svg>"),
    ).passed


def test_review_allows_loading_tooltips_decoration_and_game_interactions() -> None:
    html = _canvas(
        "Space Runner game score 0"
        '<div id="splash" class="loading">Loading Space Runner</div>'
        '<div class="tooltip">Press space</div>'
        '<div class="decoration">stars</div>'
        '<div id="enemy" class="enemy">enemy</div>',
        script=(
            'document.getElementById("splash").style.opacity=0;'
            'document.querySelector(".tooltip").remove();'
            'document.querySelector(".decoration").remove();'
            'document.getElementById("enemy").addEventListener("click",()=>enemy.remove())'
        ),
    )

    evidence = review_canvas_html("Make a Space Runner game with score 0", html)

    assert evidence.passed, evidence.to_dict()


def test_review_does_not_treat_reveal_animation_as_disappearing_content() -> None:
    html = _canvas(
        "Quarterly Revenue Q1 120 Q2 135",
        styles="@keyframes appear{from{opacity:0}to{opacity:1}} .el{animation:appear .1s forwards}",
    )

    assert review_canvas_html("Create a quarterly revenue chart showing Q1 120 and Q2 135", html).passed


@pytest.mark.parametrize(
    "styles,body",
    [
        (".label.mobile{display:none}", '<div class="label">Quarterly Revenue Q1 120 Q2 135</div>'),
        ("#label.mobile{display:none}", '<div id="label">Quarterly Revenue Q1 120 Q2 135</div>'),
        ('[data-secret="yes"]{display:none}', '<div data-secret="no">Quarterly Revenue Q1 120 Q2 135</div>'),
        (".secret:not(.shown){display:none}", '<div class="secret shown">Quarterly Revenue Q1 120 Q2 135</div>'),
        (
            ".marker + .secret{display:none}",
            '<div class="marker"></div><span></span><div class="secret">Quarterly Revenue Q1 120 Q2 135</div>',
        ),
        (
            ".secret:first-child{display:none}",
            '<div><span></span><div class="secret">Quarterly Revenue Q1 120 Q2 135</div></div>',
        ),
        ("@keyframes vanish{to{opacity:0}}", "<div>Quarterly Revenue Q1 120 Q2 135</div>"),
        (
            "@keyframes vanish{to{opacity:0}} .secret{animation:vanish .01s}",
            '<div class="secret">Quarterly Revenue Q1 120 Q2 135</div>',
        ),
        ("", '<div style="filter:opacity(1);content-visibility:auto">Quarterly Revenue Q1 120 Q2 135</div>'),
    ],
)
def test_review_preserves_selector_conjunctions(styles: str, body: str) -> None:
    assert review_canvas_html(
        "Create a quarterly revenue chart showing Q1 120 and Q2 135",
        _canvas(body, styles=styles),
    ).passed


def test_review_accepts_the_canonical_deterministic_canvas_renderer() -> None:
    from thomas.server.chat_delegation_canvas import build_canvas_html

    spec = """
    {
      "stage": {"w": 720, "h": 520, "bg": "#ffffff"},
      "title": "Quarterly Revenue",
      "elements": [
        {"id":"title","kind":"text","label":"Quarterly Revenue","geometry":{"x":80,"y":50},"motion":"rise-fade"},
        {"id":"q1","kind":"text","label":"Q1","geometry":{"x":80,"y":100},"motion":"rise-fade"},
        {"id":"v1","kind":"number","value":120,"geometry":{"x":160,"y":100},"motion":"count-up"},
        {"id":"q2","kind":"text","label":"Q2","geometry":{"x":80,"y":170},"motion":"rise-fade"},
        {"id":"v2","kind":"number","value":135,"geometry":{"x":160,"y":170},"motion":"count-up"}
      ],
      "sequence":{"order":["title","q1","v1","q2","v2"],"stagger_ms":70}
    }
    """

    evidence = review_canvas_html(
        "Create a polished chart showing Quarterly Revenue Q1 120 and Q2 135",
        build_canvas_html(spec),
    )

    assert evidence.passed, evidence.to_dict()


def test_review_rejects_prompt_evidence_that_exists_only_in_transient_ui() -> None:
    html = _canvas('<div class="tooltip">Quarterly Revenue Q1 120 Q2 135</div>Fruit 42')

    codes = _issue_codes("Create a quarterly revenue chart showing Q1 120 and Q2 135", html)

    assert "requested_values_missing" in codes
    assert "subject_mismatch" in codes
