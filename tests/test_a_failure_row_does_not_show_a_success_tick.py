"""A row that says something failed must not be drawn with a success tick.

Seen on screen. Opening a deliverable deep link whose task no longer exists
(``/?forge_code=fc_does_not_exist_00000``) produced, in Code mode::

    ✓  Technical check failed
       not found

A green ``ph-check-circle`` directly above the word "failed", and the row missing
the ``is-error`` class that colours it -- measured on the element itself::

    before   heading 'Technical check failed'  icon 'ph ph-check-circle'
             glyph '✓'  colour rgb(139, 140, 255)  is-error False
    after    heading 'Something went wrong'    icon 'ph ph-warning'
             glyph '⚠'  colour rgb(255, 154, 154)  is-error True

Two causes, both fixed here.

**The icon and the words came from different failure tests.** ``eventHtml``
asked ``is_error === true``; ``groupedTechnicalEvents`` asked
``is_error === true || kind === 'error'``; ``technicalHeading`` sided with the
second. A live ``error`` event -- the shape ``pushLiveEvent({ type: 'error' })``
emits, which never sets ``is_error`` -- therefore got failure wording and a
success icon. Live-vs-saved is why it survived: the grouped path was already
right, so the finished transcript of the same run looked correct and only the
run being watched lied. The two predicates are now one function.

**"Technical check failed" claimed a check ran.** Nothing was checked; the
conversation does not exist. This is the same overloading of the word that a
comment in that file already documents for ``tool_result`` ("Checked tool
result" above a file WRITE) and ``meta`` ("Verified the result" above a revert)
-- those two were cleaned up and ``error`` was left behind. "check" means an
engine check everywhere else in this UI, and the verdict card counts those.
"""

from __future__ import annotations

import re
from pathlib import Path

# eventFailed moved when the render cluster left unified_code_mode.js for its
# size ceiling. One predicate is the whole point of this file, so it is looked
# for across both halves -- finding it in neither must fail, not pass quietly.
_WEB_JS = Path(__file__).resolve().parents[1] / "thomas" / "server" / "web" / "js"
SOURCE = chr(10).join(
    (_WEB_JS / name).read_text(encoding="utf-8") for name in ("unified_code_mode.js", "unified_code_events.js")
)


def _without_comments() -> str:
    """The code, minus comments.

    This change is documented directly above itself and quotes the old wording
    verbatim, so a scan that reads its own comment would pass on the strength of
    prose rather than behaviour.
    """

    out = []
    for line in SOURCE.splitlines():
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("/*"):
            continue
        out.append(line)
    return "\n".join(out)


CODE = _without_comments()
# Since the 2026-10 Build redesign a technical event is drawn as a work row by
# unified_code_cards.js: no icon, a tint and a ✓/✕ mark instead. The cards never
# judge an event themselves -- the event cluster hands them its predicate.
CARDS = (_WEB_JS / "unified_code_cards.js").read_text(encoding="utf-8")


def test_one_failure_predicate_decides_both_the_icon_and_the_words() -> None:
    """Every failure look must route through the shared predicate.

    The bug was not a wrong predicate, it was two of them. Pinning the shared
    function is what stops a third renderer from drifting again.
    """

    assert "function eventFailed(" in CODE, (
        "the shared failure predicate `eventFailed` is gone; the icon and the heading are free to disagree again"
    )

    # The work row's tint and its mark are driven by ONE resolved flag, and
    # that flag is the caller's predicate, never a bare is_error test.
    assert "failed: event => eventFailed(event)" in CODE, (
        "the event cluster no longer hands its failure predicate to the work rows"
    )
    row = CARDS.split("function workRowHtml(", 1)[1].split("\n  function ", 1)[0]
    assert "options.failed(ev)" in row, "a work row decides failure without the caller's predicate"
    assert re.search(r"\$\{\s*failed\s*\?\s*' is-error'", row), "a failed row is no longer tinted from the flag"
    face = CARDS.split("function workRowFace(", 1)[1].split("\n  function ", 1)[0]
    assert re.search(r"options\.failed\s*\?\s*'✕'\s*:\s*'✓'", face), "the ✓/✕ mark no longer follows the flag"
    assert "is_error" not in CARDS, "the cards judge an event's failure on their own -- a second predicate"

    # ...and every flag in the event cluster must come from eventFailed.
    for match in re.finditer(r"const (\w*[Ff]ailed) = ([^;]+);", CODE):
        name, expression = match.group(1), match.group(2)
        assert "eventFailed(" in expression, (
            f"`{name}` is computed as `{expression.strip()}` instead of calling "
            "eventFailed(). That is exactly how the icon and the heading came "
            "to disagree: eventHtml tested `is_error === true` while the "
            "grouped path also treated kind === 'error' as a failure."
        )


def test_an_error_event_counts_as_a_failure() -> None:
    """`kind === 'error'` alone must be enough, with no `is_error` present.

    `pushLiveEvent({ type: 'error', text: ... })` -- used for a failed Code
    request, a failed file preview, and every error `safely()` catches -- sets
    no `is_error` field at all.
    """

    match = re.search(r"function eventFailed\([^)]*\)\s*\{(.*?)\n  \}", CODE, re.S)
    assert match, "eventFailed is no longer a recognisable function"
    body = match.group(1)
    assert "'error'" in body, (
        "eventFailed no longer treats kind === 'error' as a failure, so a live "
        "error row renders under a success tick again"
    )
    assert "is_error" in body, (
        "eventFailed no longer honours is_error, so a tool result that reports its own failure renders as a success"
    )


def test_an_error_is_not_reported_as_a_failed_check() -> None:
    """Nothing was checked. Saying so asserts work that never happened."""

    assert "Technical check failed" not in CODE, (
        "a technical row still reads 'Technical check failed'. For the "
        "dead-deep-link case nothing was checked -- the task does not exist -- "
        "so this claims a verification ran on work that was never done. Same "
        "overloading of 'check' that was already fixed for tool_result and meta."
    )


def test_a_failed_tool_call_is_named_rather_than_called_a_check() -> None:
    """The tool's own name is present on most of these and says more."""

    assert "'Tool call failed'" in CODE, (
        "the fallback heading for a tool result that returned an error is gone; "
        "it previously read 'Technical check failed', which called a failed "
        "tool call a failed check"
    )


def test_a_successful_row_still_gets_the_tick() -> None:
    """The opposite failure: warning-looks on everything.

    A normal `tool`/`tool_result`/`meta` row has no `is_error` and a kind other
    than 'error', so it must still resolve to false and keep its success mark
    (the work row's ✓, since the 2026-10 redesign replaced the icon).
    """

    assert "'✓'" in CARDS, (
        "the success mark is gone entirely -- every technical row now reads as "
        "a failure, which is the same lie in the other direction"
    )
    match = re.search(r"function eventFailed\([^)]*\)\s*\{(.*?)\n  \}", CODE, re.S)
    body = match.group(1)
    assert "return" in body and "true" not in body.split("return", 1)[1].split("||")[0].replace(
        "event.is_error === true", ""
    ), "eventFailed appears to return a constant rather than testing the event"
