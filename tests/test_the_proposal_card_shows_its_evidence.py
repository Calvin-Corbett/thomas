"""The card must show the evidence, not just the verdict.

An ask you cannot check is not a question, it is a notification with buttons --
and approving those out of habit is the rubber stamp this whole runtime exists to
remove. So the card carries how many times the gate was checked, how often it
actually stopped anything, and how often the user overrode it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS = REPO_ROOT / "tests" / "web_node" / "work_lane_proposal_card.mjs"
WORK_SUPPORT_JS = REPO_ROOT / "thomas" / "server" / "web" / "js" / "unified_work_support.js"


def test_the_gate_change_card_renders_with_its_evidence() -> None:
    completed = subprocess.run(
        ["node", str(HARNESS), str(WORK_SUPPORT_JS)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert '"cardShowsEvidence":true' in completed.stdout
    assert '"emptyQueueRendersNothing":true' in completed.stdout
    assert '"cardIsOnTheBoard":true' in completed.stdout
