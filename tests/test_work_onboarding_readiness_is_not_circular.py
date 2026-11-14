"""Readiness must not be the model's own claim wearing a checker's name.

Until 2026-09-08 `onboardingConfigurationReady` (unified_work_support.js) returned
`selected_workflow_configured === true`, and `advanceOnboardingPhase`
(unified_work_mode.js) wrote that result straight back into
`selected_workflow_configured`. It read as the browser independently verifying the
model's claim about its own work; it re-read the claim. The verdict was the thing
it was meant to judge, and the Finish button was unlocked by the assertion that it
should be unlocked.

Readiness is now two independent facts -- the model's semantic judgement, and the
browser's record of the turn at which the user chose. The model keeps the semantic
call (no prose classifier replaces it); what it no longer does is certify itself.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS = REPO_ROOT / "tests" / "web_node" / "work_onboarding_readiness_is_not_circular.mjs"
WORK_SUPPORT_JS = REPO_ROOT / "thomas" / "server" / "web" / "js" / "unified_work_support.js"
WORK_JS = REPO_ROOT / "thomas" / "server" / "web" / "js" / "unified_work_mode.js"


def test_onboarding_readiness_is_not_its_own_evidence() -> None:
    completed = subprocess.run(
        ["node", str(HARNESS), str(WORK_SUPPORT_JS)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert '"readinessIsNotCircular":true' in completed.stdout
    assert '"factsAreIndependent":true' in completed.stdout
    assert '"restoreKeepsTheClick":true' in completed.stdout


def test_the_persisted_field_is_the_model_claim_not_the_composite() -> None:
    """A wiring check: readiness must not be written back into its own input.

    Driving `advanceOnboardingPhase` needs the whole adapter, so this asserts the
    assignment rather than running it. It catches the loop being reintroduced; the
    behavioural proof is in the harness above.
    """
    source = WORK_JS.read_text(encoding="utf-8")
    assert "selected_workflow_configured: modelReportedConfigured()," in source
    assert "selected_workflow_configured: onboardingConfigurationReady(" not in source
