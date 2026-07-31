"""Mentioning a page must not count as opening it in a browser.

`_unopened_page_risks` exists to say "nobody looked at this page". It decided
that by searching for the page's basename in a blob built from validation
evidence AND every event's `text` -- which includes the agent's own narration.

`fs.write_file` always emits "Wrote 4120 chars to C:/proj/orphan.html". So a page
the browser smoke never opened counted as opened purely because the agent had
said it wrote it, and every page an agent creates is described that way. The one
risk whose whole job is to catch pages nobody looked at could effectively never
fire for them.

It also re-broke what a comment three lines below claims was already fixed --
"the old global check let one opened page vouch for every other changed page" --
because a run that smoke-tested `index.html` and merely mentioned `orphan.html`
came out clean.

Measured against controls, same validations and same changed files, varying only
the transcript::

    transcript "Wrote 4120 chars to C:/proj/orphan.html"  ->  no risk   (wrong)
    transcript "Wrote 4120 chars to the second page"      ->  risk      (right)
    no events at all                                      ->  risk      (right)

The fix keeps only strings carrying a `BROWSER_SMOKE` marker. Events stay in
scope rather than being dropped, because `build_verify` emits the smoke line
both as a `tool_result` event and appended to the check's detail, and only one
of those is guaranteed to survive truncation.
"""

from __future__ import annotations

import inspect
import re

from thomas.forge.anvil import run_report
from thomas.forge.anvil.run_report import _build_rubric_mapping, _unopened_page_risks

SMOKE_OPENED_INDEX = [{"evidence": "BROWSER_SMOKE_OK: index.html: browser boot clean; boot only"}]
CHANGED = ["index.html", "orphan.html"]


def _flagged(events: list[dict[str, object]], validations=None) -> str:
    risks = _unopened_page_risks(events, validations or SMOKE_OPENED_INDEX, CHANGED)
    return " ".join(str(r.get("detail") or "") for r in risks)


def test_the_agents_own_words_do_not_count_as_a_browser_check() -> None:
    detail = _flagged(
        [{"fc": "tool_result", "name": "fs.write_file", "text": "Wrote 4120 chars to C:/proj/orphan.html"}]
    )
    assert "orphan.html" in detail, (
        "a page the browser smoke never opened is reported as opened because the "
        "agent's transcript mentions writing it. Every page an agent creates is "
        "mentioned that way, so this risk cannot fire for the pages it exists to catch."
    )


def test_a_page_the_smoke_really_opened_raises_nothing() -> None:
    """The opposite failure: flagging pages that WERE checked.

    A risk that fires on a properly verified page teaches the reader to skip the
    line, which is how a permanently-red signal ends up hiding a real one.
    """

    detail = _flagged([{"fc": "tool_result", "text": "BROWSER_SMOKE_OK: orphan.html: browser boot clean"}])
    assert "orphan.html" not in detail, (
        "a page the smoke genuinely opened is still reported as never opened"
    )
    assert not detail, f"unexpected risk raised: {detail!r}"


def test_a_marker_that_arrives_only_as_an_event_still_counts() -> None:
    """build_verify emits the smoke line as an event AND in the check detail.

    Narrowing to validation evidence alone would have lost the event-only case,
    which is why the filter tests for the marker rather than for the source.
    """

    detail = _unopened_page_risks(
        [{"fc": "tool_result", "text": "BROWSER_SMOKE_SKIPPED: browser smoke unavailable"}],
        [{"evidence": "exit 0 parsed index.html"}],
        ["index.html"],
    )
    joined = " ".join(str(r.get("detail") or "") for r in detail)
    assert "index.html" in joined, "the risk vanished when the marker arrived only as an event"
    assert "skipped" in joined, (
        "a skipped browser check is reported with the same wording as one that "
        "never ran; the owner cannot tell 'Chrome was missing' from 'nothing "
        f"was checked'. Got: {joined!r}"
    )


def test_a_skipped_check_is_not_counted_as_a_passing_one() -> None:
    """`passed` is the absence of an error, and a skip sets no error.

    So a browser smoke the engine never ran arrived flagged `passed: True` and
    was counted in the rubric evidence as "2 passed, 0 failed" on a run where
    one of the two never happened. The Code UI already excluded skips from its
    displayed count (`unified_code_results.js`: `wasSkipped`); the rubric
    evidence is a separate surface and had not been told.

    Not reproducible on a machine that has Chrome -- every real report here
    carries a real smoke -- which is exactly why it needs a test rather than an
    observation.
    """

    static = {"command": "static checks", "evidence": "exit 0 STATIC_VERIFY_OK: 1 files checked", "passed": True}
    skipped = {
        "command": "offline real-browser smoke",
        "evidence": "BROWSER_SMOKE_SKIPPED: page.html: browser smoke unavailable",
        "passed": True,
    }
    ran = {
        "command": "offline real-browser smoke",
        "evidence": "BROWSER_SMOKE_OK: page.html: browser boot clean",
        "passed": True,
    }

    def counts(validations):
        rubric = _build_rubric_mapping(
            "Build page.html", "", validations, ok=True, outcome="completed", reason=""
        )
        return " ".join(str(r.get("evidence") or "") for r in rubric)

    skipped_counts = counts([static, skipped])
    assert "1 passed" in skipped_counts and "1 skipped" in skipped_counts, (
        "a browser check the engine skipped is counted as a passing engine "
        f"check in the rubric evidence. Got: {skipped_counts!r}"
    )
    assert "2 passed" not in skipped_counts

    # Control: a smoke that really ran must still count as passed, or this only
    # shows the counter got stricter rather than more truthful.
    ran_counts = counts([static, ran])
    assert "2 passed" in ran_counts and "skipped" not in ran_counts, (
        f"a check that really ran is no longer counted as passing. Got: {ran_counts!r}"
    )


def test_a_skipped_check_does_not_cover_the_file_it_names() -> None:
    """Its evidence names the page, which silenced the coverage risk.

    `BROWSER_SMOKE_SKIPPED: wordfreq.html: ...` put the filename into
    `passing_text`, so "files changed without a matching passing validation"
    treated a check that never ran as covering the file. Same shape as the
    transcript-mention bug above: a string that merely CONTAINS the filename
    taken as proof something examined it.
    """

    source = inspect.getsource(run_report)
    passing_text = re.search(r"passing_text = \" \"\.join\((.{0,240}?)\)\n", source, re.S)
    assert passing_text, "the passing_text builder is gone"
    assert "_was_skipped" in passing_text.group(1), (
        "passing_text still counts skipped checks as passing, so a check that "
        "never ran silences the risk that says the file was never covered"
    )


def test_one_opened_page_does_not_vouch_for_another() -> None:
    """The per-page property the module already claims to have."""

    detail = _flagged([])
    assert "orphan.html" in detail, "orphan.html is unreported although only index.html was opened"
    assert "index.html" not in detail, "index.html was opened and must not be flagged"
