"""A page whose whole navigation does nothing must not pass silently.

The browser smoke clicks the navigation controls it finds and compares the page
before and after. When none of them change anything it says so -- and returns
ok, so the finding is recorded as a passing check with the sentence that matters
buried in evidence nobody expands:

    browser boot clean; boot only; note: clicked 3 navigation control(s) and the
    page never changed; the navigation may be decoration

That is the owner's Nova calculator exactly: five nav destinations that looked
finished and were inert. Verified against the real smoke on a page whose
handlers are never attached -- it produces that note and returns ok=True.

Promoted to an open risk rather than a failure. A page whose navigation is not
wired yet is a normal midpoint of a build; failing the run would send the repair
loop after a half-finished feature instead of the goal. A risk shows on the card
and steers the loop without stopping it.
"""

from __future__ import annotations

from thomas.forge.anvil.run_report import _decorative_navigation_risks

DECORATION_NOTE = (
    "BROWSER_SMOKE_OK: index.html: browser boot clean; boot only; note: clicked 3 "
    "navigation control(s) and the page never changed; the navigation may be decoration"
)
# The normal reading for whichever destination is already active. Must NOT fire.
PARTIAL_NOTE = (
    "BROWSER_SMOKE_OK: index.html: browser boot clean; nav:Conversions, nav:Graph studio; "
    "note: 1 of 5 navigation control(s) changed nothing when clicked"
)
CLEAN = "BROWSER_SMOKE_OK: index.html: browser boot clean; boot only"


def _check(evidence: str) -> list[dict]:
    return _decorative_navigation_risks([{"evidence": evidence, "passed": True}], [])


def test_a_page_whose_navigation_does_nothing_raises_a_risk() -> None:
    risks = _check(DECORATION_NOTE)

    assert len(risks) == 1, risks
    assert risks[0]["risk"] == "the navigation may be decoration"
    assert "nothing changed" in risks[0]["detail"]


def test_one_inert_control_out_of_several_does_not_fire() -> None:
    """The active destination legitimately changes nothing when re-clicked.
    Flagging that would fire on every correct page and train people to ignore
    the line."""
    assert _check(PARTIAL_NOTE) == []


def test_a_page_with_no_navigation_note_raises_nothing() -> None:
    assert _check(CLEAN) == []
    assert _check("") == []


def test_the_note_is_found_in_stream_events_too() -> None:
    """The same sentence arrives as a tool_result event on a live run, not only
    in the assembled validations."""
    risks = _decorative_navigation_risks([], [{"text": DECORATION_NOTE}])

    assert len(risks) == 1
