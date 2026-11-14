"""UI half of the w2-work-mode P0/P1/P2 findings (2026-08-05).

Runs the node harness that drives the real Work adapter + support modules:
- text typed on the Work board reaches the wizard as the first message,
- a message naming exactly one offered workflow selects it,
- a 4xx from the onboarding PATCH becomes a visible transcript row,
- assistant markdown renders (no literal asterisks),
- a configured one-workflow map shows the Create job button.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from thomas.work import WorkConflictError, WorkStore

REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS = REPO_ROOT / "tests" / "web_node" / "work_onboarding_finishable.mjs"
WORK_SUPPORT_JS = REPO_ROOT / "thomas" / "server" / "web" / "js" / "unified_work_support.js"
WORK_JS = REPO_ROOT / "thomas" / "server" / "web" / "js" / "unified_work_mode.js"
WORK_STEER_JS = REPO_ROOT / "thomas" / "server" / "web" / "js" / "unified_work_mode_steer.js"


def test_work_onboarding_ui_is_finishable_and_honest(tmp_path: Path) -> None:
    completed = subprocess.run(
        ["node", str(HARNESS), str(WORK_SUPPORT_JS), str(WORK_JS), str(WORK_STEER_JS)],
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
    proof = json.loads(completed.stdout)
    updates = proof["orderedPhaseUpdates"]
    store = WorkStore(tmp_path / "work")
    app = store.create_app({"id": "ops", "name": "Operations"})
    app_id = app["id"]
    store.append_onboarding_message(app_id, {"role": "user", "text": "Plan a dinner"})
    store.append_onboarding_message(app_id, {"role": "thomas", "text": "Which workflow?"})
    with pytest.raises(WorkConflictError) as error:
        store.update_onboarding(app_id, updates[-1])
    assert hashlib.sha256(str(error.value).encode()).hexdigest()[:12] == "6d42ff42377e"
    for update in updates:
        onboarding = store.update_onboarding(app_id, update)
    assert onboarding["phase"] == "workflow_configuration"
