"""A check that did not run must not read like a check that passed.

Every other open risk describes something that went wrong. This one describes
something that never happened: the run report said "0 open risks" while the
strongest evidence available -- loading the page in a real browser -- had been
skipped, because Chrome was missing or because nothing was found to own the
changed asset. A run could look green and still hand back a page nobody, human
or machine, had ever seen.
"""

from __future__ import annotations

from thomas.forge.anvil.run_report import build_run_report


def _risks(events, changed):
    report = build_run_report(
        events=events,
        transcript="",
        changed_files=changed,
        goal="build the page",
        definition=None,
        outcome="completed",
        returncode=0,
        ok=True,
        reason="",
    )
    return [str(item.get("risk") or "") for item in report["open_risks"]]


def _validation(evidence: str):
    return [
        {"fc": "tool", "name": "run", "text": "verify"},
        {"fc": "tool_result", "text": evidence, "is_error": False},
    ]


def test_a_skipped_browser_check_is_an_open_risk() -> None:
    events = _validation("exit 0\nBROWSER_SMOKE_SKIPPED: browser smoke unavailable (Chrome or Edge not found)")

    assert any("never opened in a browser" in risk for risk in _risks(events, ["game.html"]))


def test_a_passing_browser_check_is_not_a_risk() -> None:
    events = _validation("exit 0\nBROWSER_SMOKE_OK: game.html: browser boot clean; keyboard:ArrowRight")

    assert not any("never opened in a browser" in risk for risk in _risks(events, ["game.html"]))


def test_no_browser_check_at_all_is_still_a_risk() -> None:
    """Silence is the case that mattered: nothing in the evidence mentions a
    browser, and nothing in the report said so either."""
    events = _validation("exit 0")

    assert any("never opened in a browser" in risk for risk in _risks(events, ["game.html"]))


def test_the_risk_names_the_page() -> None:
    report = build_run_report(
        events=_validation("exit 0"),
        transcript="",
        changed_files=["arcade/game.html"],
        goal="g",
        definition=None,
        outcome="completed",
        returncode=0,
        ok=True,
        reason="",
    )
    detail = " ".join(str(item.get("detail") or "") for item in report["open_risks"])

    assert "arcade/game.html" in detail


def test_a_change_with_no_pages_is_not_flagged() -> None:
    """A project's Node scripts are not pages. Flagging them would train people
    to ignore this line, which is worse than not printing it."""
    events = _validation("exit 0")

    assert not any("never opened in a browser" in risk for risk in _risks(events, ["build.js", "tool.py"]))


def test_a_browser_check_that_ran_and_failed_is_not_called_absent() -> None:
    """A check that FAILED is the opposite of a check that never happened.

    The evidence was matched against `BROWSER_SMOKE_OK` and
    `BROWSER_SMOKE_SKIPPED`, and a failing run says neither -- it says
    `BROWSER_SMOKE_FAILED`. So it fell through to the silence branch and the
    report printed "no browser check ran for this change" directly beneath the
    failing browser check that had just examined that exact page.

    Seen on a real run: `report.html` was opened, the smoke reported
    `BROWSER_SMOKE_FAILED ... Could not load sales.csv (HTTP 404)`, and the
    open risks still claimed nothing had opened it.

    This whole risk exists to say "nobody looked". Saying it when somebody
    looked and reported a defect is a false statement in the report, and it
    dilutes the real finding sitting next to it -- the repair loop reads these
    risks, so it is told to go and open a page that was already opened instead
    of fixing what the opening found.
    """

    events = _validation(
        "exit 1\nBROWSER_SMOKE_FAILED: report.html: Error: Could not load sales.csv (HTTP 404)."
    )

    risks = _risks(events, ["report.html"])
    assert not any("never opened in a browser" in risk for risk in risks), risks


def test_a_failing_check_on_one_page_still_flags_a_different_untouched_page() -> None:
    """Suppression must be about THIS evidence, not a blanket off-switch.

    A run that changed two pages and only opened one still leaves the other
    unseen, and that is exactly what this risk is for.
    """

    events = _validation("exit 1\nBROWSER_SMOKE_FAILED: report.html: Error: something broke")

    report = build_run_report(
        events=events,
        transcript="",
        changed_files=["report.html", "orphan.html"],
        goal="g",
        definition=None,
        outcome="failed",
        returncode=1,
        ok=False,
        reason="",
    )
    unopened = [
        str(item.get("detail") or "")
        for item in report["open_risks"]
        if "never opened in a browser" in str(item.get("risk") or "")
    ]

    assert unopened, report["open_risks"]
    detail = " ".join(unopened)
    # The page nobody opened is named...
    assert "orphan.html" in detail
    # ...and the page the browser DID open and report on is not.
    assert "report.html" not in detail
