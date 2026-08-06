"""The headline verdict must not claim more than the run actually checked.

A run report carries two independent things: `validations`, which are the engine
checks that ran, and `rubric_mapping`, which is where the run says which of the
asked-for requirements it did and did not verify. The verdict line was computed
from `validations` alone.

That is how the owner's "Nova" calculator shipped with a green **Checks passed**.
Its two engine checks did pass — the second with evidence reading
`browser boot clean; boot only`, meaning it loaded the page and clicked nothing —
while its own rubric carried `status: unverified` saying no individual
requirement had been checked. Driving the app by hand found five dead nav
destinations, a dead Ctrl+K command palette, two dead icon buttons, a dead Clear
button, and `200 + 10 %` returning `2.1`. None of that could have been caught by
a check that never pressed a button. The report was honest; the headline was not.

These tests execute the shipped `unified_code_results.js` in a real browser and
assert on the rendered markup, rather than grepping the source for a keyword —
a source-text assertion would keep passing if the logic were rewritten wrongly.

The control case matters as much as the regression case: if every report were
labelled unverified the label would carry no information, so a run that really
did check its requirements must still read "Checks passed".
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

RESULTS_JS = (
    Path(__file__).resolve().parents[1]
    / "thomas"
    / "server"
    / "web"
    / "js"
    / "unified_code_results.js"
)

# Verbatim shape of the report that shipped a false green on 2026-07-29, from
# GET /api/evolve/agent/conversations/fc_20260729T162230_805ebf. Kept whole,
# including the evidence strings, because the point of the fixture is that
# everything here reads like success unless you notice "boot only" and the
# unverified rubric row.
NOVA_REPORT = {
    "attempts": [
        {
            "pass": 1,
            "goal": "build me the future of calculator apps",
            "outcome": "completed",
            "exit_state": "exit 0 - 1 file(s) changed",
        }
    ],
    "validations": [
        {
            "kind": "engine_check",
            "command": "static checks: syntax + parse + open (index.html)",
            "passed": True,
            "evidence": "exit 0 parsed index.html STATIC_VERIFY_OK: 1 files checked, 0 imported",
        },
        {
            "kind": "engine_check",
            "command": "offline real-browser smoke for changed HTML or linked web assets",
            "passed": True,
            "evidence": "BROWSER_SMOKE_OK: index.html: browser boot clean; boot only",
        },
    ],
    "open_risks": [],
    "attention_pointers": [{"target": "index.html", "why": "changed in this run", "rank": 1}],
    "rubric_mapping": [
        {
            "criterion": "complete the requested goal: build me the future of calculator apps",
            "status": "met",
            "evidence": "outcome=completed; engine checks: 2 passed, 0 failed",
        },
        {
            "criterion": "the specific requirements stated in this goal",
            "status": "unverified",
            "evidence": (
                "the goal was not written as a checklist, so no individual requirement "
                "was extracted or checked on its own"
            ),
        },
    ],
}

_PASSING_CHECK = {
    "kind": "engine_check",
    "command": "static checks",
    "passed": True,
    "evidence": "exit 0",
}


def _browser_ok() -> bool:
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False

    try:
        with sync_playwright() as p:
            p.chromium.launch(headless=True).close()
    except PlaywrightError:
        # No browser binary installed, or it cannot start in this environment.
        return False
    return True


pytestmark = pytest.mark.skipif(
    not _browser_ok(), reason="playwright chromium unavailable"
)


@pytest.fixture(scope="module")
def render():
    """Execute the real module and return its rendered run-report markup."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content("<!doctype html><html><body></body></html>")
        page.add_script_tag(content=RESULTS_JS.read_text(encoding="utf-8"))
        page.evaluate(
            """() => window.ThomasCodeResults.configure({
                 state: {activeId: 'test'},
                 esc: v => String(v == null ? '' : v)
                        .replace(/&/g, '&amp;').replace(/</g, '&lt;')
                        .replace(/>/g, '&gt;').replace(/"/g, '&quot;')
                        .replace(/'/g, '&#39;'),
                 isInternalResultPath: () => false,
                 lifecycle: {},
                 render: () => {},
               })"""
        )

        def _render(report: dict) -> str:
            return page.evaluate(
                "r => window.ThomasCodeResults.runReportHtml(r)", json.loads(json.dumps(report))
            )

        yield _render
        browser.close()


def _validation_rows(html: str) -> list[tuple[str, str, str]]:
    """(heading, glyph, evidence) for each row in the Validations section."""
    assert "<summary>Validations" in html, "the report rendered no Validations section"
    block = html.split("<summary>Validations", 1)[1].split("</details>", 1)[0]
    rows = re.findall(r'<div class="tc-code-technical(?: is-error)?">.*?</div></div>', block)
    out = []
    for row in rows:
        heading = row.split("<strong>", 1)[1].split("</strong>", 1)[0]
        glyph = re.search(r'class="ph ([a-z0-9-]+)"', row).group(1)
        out.append((heading, glyph, row.split("<code>", 1)[1].split("</code>", 1)[0]))
    return out


def _verdict(html: str) -> str:
    """The headline: the text of the <strong> inside the verdict block."""
    assert "tc-code-verdict" in html, "the report rendered without a verdict block"
    head = html.split("tc-code-verdict-text", 1)[1]
    return head.split("<strong>", 1)[1].split("</strong>", 1)[0]


def test_the_nova_report_that_shipped_a_false_green_no_longer_reads_as_passing(render) -> None:
    """The exact regression. Two engine checks passed and the rubric said the
    requirements were never checked; the headline said 'Checks passed'.

    The first fix for this replaced the headline with "Not checked against your
    ask" -- rendered directly above "2/2 checks passed", two true statements a
    normal reader took as a self-contradiction (measured on every code scenario
    of the 2026-08-05 audit). The card now leads with what WAS verified and
    scopes what was not, in one sentence, and does not repeat the pass count
    beneath a headline that already carries it."""
    html = render(NOVA_REPORT)

    assert _verdict(html) != "Checks passed"
    assert _verdict(html) == "Passed 2 automatic checks"
    assert "is-unknown" in html, "an unverified run must not carry the passing tone"
    assert "is-good" not in html
    assert "your specific ask was not separately verified" in html
    # The contradictory pair stays dead: the count lives in the headline only.
    assert "Not checked against your ask" not in html
    assert "2/2 checks passed" not in html


def test_a_run_that_verified_its_requirements_still_reads_as_passing(render) -> None:
    """The control. If every report were labelled unverified the label would
    carry no information, and a green verdict has to stay reachable."""
    html = render(
        {
            "attempts": [{"pass": 1, "goal": "g", "outcome": "completed", "exit_state": "exit 0"}],
            "validations": [_PASSING_CHECK],
            "open_risks": [],
            "rubric_mapping": [
                {"criterion": "counts down from 10", "status": "met", "evidence": "asserted"}
            ],
        }
    )

    assert _verdict(html) == "Checks passed"
    assert "is-good" in html
    assert "unverified" not in html


def test_the_card_names_the_requirements_nobody_checked(render) -> None:
    """The headline says something went unchecked; this says WHICH.

    Before, the answer sat behind two closed disclosures under a section headed
    "Rubric mapping", which gives no hint it holds it -- measured at
    closedDisclosuresToOpen = 2 on a card whose entire point was that six things
    went unverified.
    """
    html = render(
        {
            "attempts": [{"pass": 1, "goal": "g", "outcome": "completed", "exit_state": "exit 0"}],
            "validations": [_PASSING_CHECK],
            "open_risks": [],
            "rubric_mapping": [
                {"criterion": "the run finished without error", "status": "met", "evidence": "e"},
                {"criterion": "Opening balance is 1000.00", "status": "unverified", "evidence": "e"},
                {"criterion": "Sorting recomputes the balance", "status": "unverified", "evidence": "e"},
            ],
        }
    )

    assert "Not checked:" in html
    assert "Opening balance is 1000.00" in html
    assert "Sorting recomputes the balance" in html
    # The met row is not a thing nobody checked.
    assert html.count("the run finished without error") == 0 or "Not checked: the run finished" not in html


def test_only_two_requirements_are_named_and_each_stays_readable(render) -> None:
    """Three names starved the last one: against real criteria the line rendered
    "... · So there are 3 visible headers over 4 visib... · A..." -- a stub that
    names nothing. Two, clipped at 38, keeps both legible."""
    long_names = [
        "The Description header is hidden, but the Description cells are still shown",
        "So there are 3 visible headers over 4 visible columns, each shifted one place left",
        "AMOUNT ends up over the description and BALANCE over the amount",
        "A fourth requirement that must not appear on the face of the card",
    ]
    html = render(
        {
            "attempts": [{"pass": 1, "goal": "g", "outcome": "completed", "exit_state": "exit 0"}],
            "validations": [_PASSING_CHECK],
            "open_risks": [],
            "rubric_mapping": [
                {"criterion": name, "status": "unverified", "evidence": "e"} for name in long_names
            ],
        }
    )

    line = html.split('tc-code-verdict-unchecked">', 1)[1].split("</small>", 1)[0]
    assert line.count("·") == 1, f"expected exactly two names on the line: {line!r}"
    assert "A fourth requirement" not in line
    # Every name shown carries real words, not an initial and an ellipsis.
    for part in line.replace("Not checked: ", "").split(" · "):
        assert len(part.replace("…", "").strip()) >= 20, f"unreadable stub on the card: {part!r}"
    # The honest total still comes from the counts line above.
    assert "4 parts of your ask were not separately verified" in html


def test_no_unchecked_line_when_everything_was_verified(render) -> None:
    html = render(
        {
            "attempts": [{"pass": 1, "goal": "g", "outcome": "completed", "exit_state": "exit 0"}],
            "validations": [_PASSING_CHECK],
            "open_risks": [],
            "rubric_mapping": [{"criterion": "c", "status": "met", "evidence": "e"}],
        }
    )

    assert "tc-code-verdict-unchecked" not in html
    assert "Not checked:" not in html


def test_a_run_with_no_checks_at_all_says_so(render) -> None:
    html = render(
        {
            "attempts": [{"pass": 1, "goal": "g", "outcome": "completed", "exit_state": "exit 0"}],
            "validations": [],
            "open_risks": [{"risk": "nothing ran", "detail": "provider overloaded"}],
            "rubric_mapping": [],
        }
    )

    assert _verdict(html) == "Nothing was checked"
    assert "is-unknown" in html


def test_a_failed_check_outranks_an_unverified_requirement(render) -> None:
    """Severity order: a check that actually failed is worse news than one that
    never ran, and must not be softened into 'not checked'."""
    html = render(
        {
            "attempts": [{"pass": 1, "goal": "g", "outcome": "failed", "exit_state": "exit 1"}],
            "validations": [
                _PASSING_CHECK,
                {"kind": "engine_check", "command": "smoke", "passed": False, "evidence": "exit 1"},
            ],
            "open_risks": [],
            "rubric_mapping": [{"criterion": "c", "status": "unverified", "evidence": "e"}],
        }
    )

    assert _verdict(html) == "Some checks failed"
    assert "is-bad" in html
    # The unverified requirement is still reported, just not as the headline.
    assert "1 requirement unverified" in html


_SKIPPED_SMOKE = {
    "kind": "engine_check",
    "command": "offline real-browser smoke for changed HTML or linked web assets",
    # This is what the engine really emits when no browser is installed:
    # build_verify prefixes BROWSER_SMOKE_SKIPPED and leaves is_error unset, and
    # run_report derives `passed` from the absence of an error -- so a check that
    # never ran arrives flagged True.
    "passed": True,
    "evidence": "BROWSER_SMOKE_SKIPPED: no chrome or edge binary found",
}


def test_a_skipped_check_is_not_counted_as_a_passing_one(render) -> None:
    """Latent on this machine -- Chrome is present, so 0 of 47 real reports carry
    a skip. On a fresh install without browsers every web run would have read
    "2/2 checks passed" with one of the two never having run."""
    html = render(
        {
            "attempts": [{"pass": 1, "goal": "g", "outcome": "completed", "exit_state": "exit 0"}],
            "validations": [_PASSING_CHECK, _SKIPPED_SMOKE],
            "open_risks": [
                {"risk": "a changed page was never opened in a browser", "detail": "index.html"}
            ],
            "rubric_mapping": [{"criterion": "c", "status": "met", "evidence": "e"}],
        }
    )

    assert "2/2 checks passed" not in html, "a skipped check was counted as passing"
    assert "1/1 check passed" in html
    assert "1 check skipped" in html
    # The unopened-page risk is what run_report already raises here, so the tone
    # was never the problem -- only the count.
    assert "is-warn" in html
    assert "1 open risk" in html


def test_a_run_whose_only_check_was_skipped_says_nothing_was_checked(render) -> None:
    """The edge the count fix creates: every check skipped is indistinguishable
    from no checks at all, and must read that way rather than as a pass."""
    html = render(
        {
            "attempts": [{"pass": 1, "goal": "g", "outcome": "completed", "exit_state": "exit 0"}],
            "validations": [_SKIPPED_SMOKE],
            "open_risks": [],
            "rubric_mapping": [{"criterion": "c", "status": "met", "evidence": "e"}],
        }
    )

    assert _verdict(html) == "Nothing was checked"
    assert "is-unknown" in html
    assert "1 check skipped" in html
    assert "1/1 check passed" not in html


def test_the_word_skipped_in_unrelated_evidence_does_not_downgrade_a_pass(render) -> None:
    """The matcher keys on the engine's own marker. Evidence like
    "1 files checked, 1 skipped" is a real static-verify string and means the
    check ran."""
    html = render(
        {
            "attempts": [{"pass": 1, "goal": "g", "outcome": "completed", "exit_state": "exit 0"}],
            "validations": [
                {
                    "kind": "engine_check",
                    "command": "static checks",
                    "passed": True,
                    "evidence": "exit 0 STATIC_VERIFY_OK: 2 files checked, 1 skipped",
                }
            ],
            "open_risks": [],
            "rubric_mapping": [{"criterion": "c", "status": "met", "evidence": "e"}],
        }
    )

    assert _verdict(html) == "Checks passed"
    assert "1/1 check passed" in html
    assert "check skipped" not in html


def test_the_row_for_a_skipped_check_does_not_say_the_check_passed(render) -> None:
    """The headline learned to separate skipped from passed; the per-check row
    never did, and the row is what a reviewer opens to see WHICH check.

    Rendered from the same report, on the same card:

        face of the card   "1/1 check passed · 1 check skipped"   (honest)
        Validations (2)    "Check passed"  ph-check-circle        (the run)
                           "Check passed"  ph-check-circle        <- never ran

    After: the second row reads "Check skipped" under ph-info, and the first is
    untouched. `passed` is the absence of an error, so a skipped check arrives
    flagged true -- the evidence string is the only thing that knows.
    """
    html = render(
        {
            "attempts": [{"pass": 1, "goal": "g", "outcome": "completed", "exit_state": "exit 0"}],
            "validations": [_PASSING_CHECK, _SKIPPED_SMOKE],
            "open_risks": [],
            "rubric_mapping": [{"criterion": "c", "status": "met", "evidence": "e"}],
        }
    )
    rows = _validation_rows(html)

    assert len(rows) == 2
    assert [heading for heading, _, _ in rows] == ["Check passed", "Check skipped"]
    # The check that really ran keeps its tick; the one that did not must not
    # borrow it -- a green tick beside "skipped" reads as a pass at a glance.
    assert rows[0][1] == "ph-check-circle"
    assert rows[1][1] != "ph-check-circle"
    assert "BROWSER_SMOKE_SKIPPED" in rows[1][2]
    # A skip is not a failure either: no error styling, and the count stands.
    assert "1/1 check passed" in html
    assert "1 check skipped" in html


def test_a_failing_check_still_reads_as_failed_even_with_a_skip_marker(render) -> None:
    """The severity control. Skipped must not soften a check that actually ran
    and failed, and the word "skipped" in ordinary static-verify evidence
    ("2 files checked, 1 skipped") must not relabel a genuine pass."""
    html = render(
        {
            "attempts": [{"pass": 1, "goal": "g", "outcome": "failed", "exit_state": "exit 1"}],
            "validations": [
                {
                    "kind": "engine_check",
                    "command": "static checks",
                    "passed": True,
                    "evidence": "exit 0 STATIC_VERIFY_OK: 2 files checked, 1 skipped",
                },
                {
                    "kind": "engine_check",
                    "command": "offline real-browser smoke",
                    "passed": False,
                    "evidence": "BROWSER_SMOKE_SKIPPED: ran, then the page threw",
                },
            ],
            "open_risks": [],
            "rubric_mapping": [{"criterion": "c", "status": "met", "evidence": "e"}],
        }
    )
    rows = _validation_rows(html)

    assert [heading for heading, _, _ in rows] == ["Check passed", "Check failed"]
    assert rows[1][1] == "ph-warning"
    assert 'is-error"' in html.split("<summary>Validations", 1)[1].split("</details>", 1)[0]


def test_open_risks_do_not_hide_behind_an_unverified_headline(render) -> None:
    """Whichever headline wins, the risk count stays on the card."""
    html = render(
        {
            "attempts": [{"pass": 1, "goal": "g", "outcome": "completed", "exit_state": "exit 0"}],
            "validations": [_PASSING_CHECK],
            "open_risks": [{"risk": "unhandled input", "detail": "percent key"}],
            "rubric_mapping": [{"criterion": "c", "status": "unverified", "evidence": "e"}],
        }
    )

    assert _verdict(html) == "Passed 1 automatic check"
    assert "1 open risk" in html
