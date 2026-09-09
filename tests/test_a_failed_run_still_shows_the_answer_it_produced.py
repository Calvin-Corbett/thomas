"""A produced answer is never suppressed, and a stop is never dressed as a failure.

Four measured defects in one rendering seam (``unified_code_events.js``):

1. A run filed as failed whose transcript nevertheless carried a ``final`` event
   with text rendered ONLY ``failureSummary()`` -- ``turnHtml`` threw the model's
   produced answer away, and ``progressEvents`` filtered the final event out of
   the narrative, so the text existed nowhere on screen. That is the auto-reject
   shape applied to rendering: work the model produced, discarded by plumbing.

2. A deliberately STOPPED run (the recorder files ``outcome: 'stopped'`` with
   reason ``"stopped by you"``) rendered through the red failure pipeline on
   reload -- "The Code task stopped before it finished — stopped by you..." in
   error styling, about an interruption the user asked for.

3. The activity header counted every ``is_error`` tool_result as "N issues" even
   on a flawless run. Measured on a perfect clock build: "8 issues", of which 7
   were the model's own scratch-verifier retries (recovered) and 1 the expected
   first read probe of a brand-new empty project (an existence check).

4. That first read probe also rendered as an alarming red row.

The controls pin what must NOT change: the stale review-limit excuse is not an
answer and stays replaced by the authoritative summary; a genuine failure keeps
the red pipeline; a failed run's tool errors stay "issues"; a later failing read
is a real recovered attempt, not a probe.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EVENTS_JS = REPO_ROOT / "thomas" / "server" / "web" / "js" / "unified_code_events.js"
HARNESS = REPO_ROOT / "tests" / "web_node" / "code_failed_and_stopped_render.mjs"


def _drive() -> dict[str, str]:
    result = subprocess.run(
        ["node", str(HARNESS), str(EVENTS_JS)],
        capture_output=True,
        check=False,
        text=True,
        # Node writes UTF-8; without this, Windows decodes the report as
        # cp1252 and any em dash in the wording arrives mangled.
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _reply_area(html: str) -> str:
    """Everything from the first reply div onward -- the part the owner reads."""
    at = html.find('tc-code-reply')
    assert at >= 0, f"no reply rendered at all: {html[:400]}"
    return html[at:]


def test_a_failed_run_renders_the_answer_it_produced() -> None:
    html = _drive()["failedWithAnswer"]
    assert "THE-PRODUCED-ANSWER" in html, (
        "the transcript carries a final event with text, and the rendered turn "
        "does not contain it -- the produced answer was suppressed"
    )
    # The failure is still told, alongside -- never instead.
    assert "repair attempts" in html, "the failure note vanished with the fix"
    # The answer itself must not wear the error styling; the note does.
    answer_div = re.search(r'<div class="tc-code-reply">[^<]*THE-PRODUCED-ANSWER', html)
    assert answer_div, "the produced answer is rendered inside the error styling"


def test_the_stale_review_limit_excuse_is_still_not_an_answer() -> None:
    html = _drive()["failedWithStaleExcuse"]
    assert "review budget forbids" not in html, (
        "the model's budget excuse is back on screen; the authoritative "
        "verification summary must replace it (existing contract)"
    )
    assert "repair attempts" in html


def test_a_stopped_run_is_not_dressed_as_a_failure() -> None:
    report = _drive()
    for key in ("stoppedByReason", "stoppedByOutcome"):
        area = _reply_area(report[key])
        assert "is-error" not in area, (
            f"{key}: a run the user deliberately stopped renders through the "
            "red failure pipeline"
        )
        assert "Stopped" in area, f"{key}: the stop is not named"
        # Honest wording: the run did not fail, and must not claim it did.
        assert "The Code task stopped before it finished" not in area, (
            f"{key}: the stopped run still reads the failure-pipeline sentence"
        )
    # Detail the recorder attached (how much work was already done) survives.
    assert "2 file(s) had already changed" in _reply_area(report["stoppedByReason"])
    # Control: a genuine failure keeps the red pipeline.
    assert "is-error" in _reply_area(report["genuinelyFailed"])


def test_recovered_attempts_on_an_ok_run_are_not_called_issues() -> None:
    report = _drive()
    ok_html = report["okWithRecoveredAttempts"]
    assert "7 failed attempts, recovered" in ok_html, (
        "an OK run's recovered tool errors are not labelled as recovered"
    )
    assert not re.search(r"\b7 issues\b", ok_html), (
        "a flawless run still advertises its recovered retries as issues"
    )
    # The alarm styling belongs to runs that actually failed.
    assert "has-issues" not in ok_html
    # Control: a failed run's tool errors stay issues (the failing tool_result
    # plus the error event: two of them).
    assert re.search(r"\b2 issues\b", report["failedWithIssues"])
    assert "recovered" not in report["failedWithIssues"]


def test_the_first_read_probe_of_an_empty_project_is_a_neutral_note() -> None:
    report = _drive()
    probe_html = report["okWithFirstProbe"]
    assert "tc-code-technical is-error" not in probe_html, (
        "the expected first read probe of a brand-new project renders as an "
        "alarming red row"
    )
    # It is not counted as anything alarming either: no issues, no failed
    # attempts -- the run was flawless.
    assert "issue" not in probe_html and "failed attempt" not in probe_html
    # Full detail stays available: the raw probe text is still in the log.
    assert "index.html not found" in probe_html
    # Control: a LATER failing read is a real recovered attempt.
    later = report["okWithLaterFailure"]
    assert "1 failed attempt, recovered" in later, (
        "the probe exemption swallowed a real mid-run failure"
    )
