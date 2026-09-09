"""A page whose script the runtime refuses must not be reported as boot clean.

`blocktown-84.html` loads three.js from a CDN. Through Thomas's own artifact
route, measured on conversation ``fc_20260728T184945_a97729``::

    requestfailed  https://cdnjs.cloudflare.com/.../three.min.js :: csp
    window.THREE   undefined
    the only button, "Deploy to Blocktown", disabled
    red text       "The 3D engine could not load. Check your connection and refresh."

while ``smoke_html_artifacts`` returned::

    ok=True  "blocktown-84.html: browser boot clean; boot only;
              1 external resource(s) not fetched offline"

The exemption that produced that line was added deliberately, on the premise
that "a page that loads three.js from a CDN could never pass -- and blocktown-84
does exactly that. Failing it would say 'your game is broken' about a game that
works." The premise is false: the artifact preview CSP lists no remote origin in
script-src, style-src, img-src, font-src or connect-src, so the reference is
refused there permanently. The word "offline" framed a permanent runtime block
as an artifact of the harness's own DNS mapping.

Two heuristics had honest reasons to stay quiet, which is why nothing else
caught it: the canvas never got a context, so paint reads "unverifiable" rather
than "blank"; and ``body_text_chars > 0`` was satisfied partly BY THE ERROR
MESSAGE ITSELF.

``ok`` stays True on purpose, and the last test here pins that. Depending on a
CDN inside an offline sandbox is the MODEL's mistake; failing the run for it
would make this a rejector that grades the model instead of a report that tells
the truth. Only the wording changed -- and it now names the remedy, so the
repair loop stops swapping CDN hosts (the real run swapped jsdelivr -> jsdelivr
-> cdnjs across three passes, none of which could ever have worked).
"""

from __future__ import annotations

import inspect

from thomas.forge.anvil import web_artifact_smoke

SOURCE = inspect.getsource(web_artifact_smoke)


def _summary_builder_source() -> str:
    """The body of the function that assembles the pass summary, comments stripped.

    Comments are stripped because this change is documented directly above
    itself and the documentation quotes the old wording verbatim -- a scan that
    reads its own comment would fail forever, or pass forever, on the strength
    of prose.
    """

    return "\n".join(
        line for line in SOURCE.splitlines() if not line.strip().startswith("#")
    )


def test_a_blocked_external_reference_is_not_described_as_offline() -> None:
    body = _summary_builder_source()
    assert "not fetched offline" not in body, (
        "the smoke still calls a blocked external resource 'not fetched "
        "offline', which tells the reader it is an artifact of the test "
        "environment. It is not: the artifact preview CSP allows no remote "
        "origin, so the reference fails for the owner too, permanently."
    )


def test_the_summary_says_it_will_not_load_for_the_owner_either() -> None:
    body = _summary_builder_source()
    assert "will not load for you" in body, (
        "the blocked-resource line no longer tells the owner the resource fails "
        "for them as well; without that the line reads as a harness caveat"
    )


def test_the_summary_names_the_remedy() -> None:
    """The repair loop needs an action it can actually perform.

    Without one it swapped CDN hosts three times in a row on the real run.
    Vendoring the library locally is the only fix that can work.
    """

    body = _summary_builder_source()
    assert "vendor" in body.lower(), (
        "the blocked-resource line does not name the fix (vendor the library "
        "into the project folder), so the repair loop has nothing actionable "
        "and will keep swapping CDN hosts"
    )


def test_a_clean_page_still_reads_as_boot_clean() -> None:
    """The opposite failure: making every page look suspect.

    A page with no external references must keep its plain, unqualified line.
    """

    body = _summary_builder_source()
    assert "browser boot clean" in body, (
        "the clean-page summary lost its 'browser boot clean' wording, so pages "
        "with nothing wrong now read as though something is"
    )


def test_it_still_returns_ok_rather_than_rejecting_the_run() -> None:
    """Pinned deliberately: this reports, it does not reject.

    A CDN dependency in an offline sandbox is the model's mistake. Turning this
    into a failure would grade the model rather than fix Thomas, and would block
    runs whose deliverable is otherwise fine. If someone later flips it, that
    should be a deliberate decision that has to delete this test, not a quiet
    edit to a return value.
    """

    body = _summary_builder_source()
    marker = "external resource(s) will not load for you"
    index = body.find(marker)
    assert index != -1, "the blocked-resource branch is gone"
    window = body[max(0, index - 400):index]
    assert "return True, (" in window, (
        "the blocked-resource branch no longer returns True -- the smoke now "
        "REJECTS runs whose page references a CDN, which grades the model "
        "rather than reporting honestly"
    )
