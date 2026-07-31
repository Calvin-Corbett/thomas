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

from thomas.forge.anvil.run_report import _unopened_page_risks

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


def test_one_opened_page_does_not_vouch_for_another() -> None:
    """The per-page property the module already claims to have."""

    detail = _flagged([])
    assert "orphan.html" in detail, "orphan.html is unreported although only index.html was opened"
    assert "index.html" not in detail, "index.html was opened and must not be flagged"
