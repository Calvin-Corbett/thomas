"""UI half of the w2-work-mode P0/P1/P2 findings (2026-08-05).

Runs the node harness that drives the real Work adapter + support modules:
- text typed on the Work board reaches the wizard as the first message,
- a message naming exactly one offered workflow selects it,
- a 4xx from the onboarding PATCH becomes a visible transcript row,
- assistant markdown renders (no literal asterisks),
- a configured one-workflow map shows the Create job button.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS = REPO_ROOT / "tests" / "web_node" / "work_onboarding_finishable.mjs"
WORK_SUPPORT_JS = REPO_ROOT / "thomas" / "server" / "web" / "js" / "unified_work_support.js"
WORK_JS = REPO_ROOT / "thomas" / "server" / "web" / "js" / "unified_work_mode.js"


def test_work_onboarding_ui_is_finishable_and_honest() -> None:
    completed = subprocess.run(
        ["node", str(HARNESS), str(WORK_SUPPORT_JS), str(WORK_JS)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert '"composerTextCarried":true' in completed.stdout
    assert '"namedSelectionAccepted":true' in completed.stdout
    assert '"ambiguityStaysUnselected":true' in completed.stdout
    assert '"fourXxIsVisible":true' in completed.stdout
    assert '"markdownRenders":true' in completed.stdout
    assert '"oneWorkflowFinishable":true' in completed.stdout
