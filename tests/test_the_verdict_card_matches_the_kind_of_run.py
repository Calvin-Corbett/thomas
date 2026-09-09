"""The verdict card must grade the kind of run it is actually looking at.

Three observed variants, all from the 2026-08-05 audit, all on the same card:

* An explain-only run (outcome ``conversation`` — an answer, zero changed
  files) wore a full build-verification scorecard, complete with two "open
  risks" manufactured by the harness's own bookkeeping. There was no build to
  verify, and the card graded one anyway.
* A stopped run read "Nothing was checked · 1 requirement unverified · 2 open
  risks" — requirement-unverified and open-risk language about a run the
  person ended on purpose before verification could happen.
* The Nova shape: headline "Not checked against your ask" rendered directly
  above "2/2 checks passed · 1 requirement unverified · no open risks". Both
  halves were individually true and the juxtaposition read as a
  self-contradiction to a normal reader.

These tests execute the shipped ``unified_code_results.js`` in node (the
harness beside this file) and assert on the rendered markup. The face of the
card — the always-visible ``<summary>`` — is asserted separately from the
expandable details, because the details are the raw record and stay complete;
it is the face that must stop contradicting itself.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS_JS = REPO_ROOT / "thomas" / "server" / "web" / "js" / "unified_code_results.js"
HARNESS = REPO_ROOT / "tests" / "web_node" / "run_report_outcome_card.mjs"


def _rendered() -> dict[str, str]:
    result = subprocess.run(
        ["node", str(HARNESS), str(RESULTS_JS)],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _face(html: str) -> str:
    """The always-visible summary block — what a reader sees without clicking."""
    assert "<summary>" in html, f"no card face in: {html[:200]!r}"
    return html.split("<summary>", 1)[1].split("</summary>", 1)[0]


def test_an_answer_gets_no_build_verification_scorecard() -> None:
    """A run whose outcome is ``conversation`` produced an answer, not a build.
    Grading the answer with build checks manufactured every number on the card:
    nothing was supposed to be checked, so every count read as a defect."""
    html = _rendered()["conversation"]

    assert "tc-code-verdict" not in html, "an answer run still renders a verdict scorecard"
    assert "open risk" not in html
    assert "unverified" not in html
    assert "checked" not in html.lower() or "nothing to verify" in html.lower()
    # Not silence either: one line says WHY there is nothing to verify.
    assert "answer" in html.lower()


def test_a_stopped_run_is_not_graded_as_an_unverified_build() -> None:
    """The person ended the run. The face says that — and stops there. The
    observed card said "Nothing was checked · 1 requirement unverified · 2 open
    risks", three charges against a run nobody let finish."""
    html = _rendered()["stopped"]
    face = _face(html)

    assert "Stopped before verification could run" in face
    assert "unverified" not in face
    assert "open risk" not in face
    assert "Nothing was checked" not in face


def test_the_contradictory_headline_pair_can_no_longer_be_produced() -> None:
    """Lead with what WAS verified, then scope what was not — one coherent
    sentence. The old face put "Not checked against your ask" directly above
    "2/2 checks passed", and a normal reader cannot hold both."""
    html = _rendered()["unverified"]
    face = _face(html)

    assert "Not checked against your ask" not in face
    assert "Passed 2 automatic checks" in face
    assert "your specific ask was not separately verified" in face
    # Still not dressed as a full green: the tone stays unknown, not good.
    assert "is-unknown" in html
    assert "is-good" not in html


def test_a_fully_verified_run_keeps_its_plain_green() -> None:
    """The control. If every card were softened, the wording would carry no
    information — a run that really checked its ask still reads as passing."""
    html = _rendered()["verified"]
    face = _face(html)

    assert "Checks passed" in face
    assert "is-good" in html
    assert "unverified" not in html
