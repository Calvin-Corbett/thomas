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
