from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_site_release_pull_request_trigger_is_not_branch_or_path_filtered() -> None:
    text = _read(".github/workflows/site-release.yml")
    assert re.search(r"(?m)^on:\s*$", text)
    assert re.search(r"(?m)^\s+pull_request:\s*$", text)
    assert re.search(r"(?m)^\s+push:\s*$", text)
    assert not re.search(r"pull_request:\s*\n\s+branches\s*:", text, flags=re.MULTILINE)
    assert not re.search(r"pull_request:\s*\n\s+paths\s*:", text, flags=re.MULTILINE)


def test_site_release_enforces_visual_proof_gate() -> None:
    text = _read(".github/workflows/site-release.yml")
    assert "Resolve diff range" in text
    assert "Visual proof gate" in text
    assert "python3 scripts/check_site_visual_proof.py" in text
    assert "--base \"${{ steps.diff.outputs.base }}\"" in text
    assert "--head \"${{ steps.diff.outputs.head }}\"" in text
    assert "--json > site-visual-proof-gate.json" in text
    assert "id: visualproof" in text
    assert "Install Playwright browser" in text
    assert "npx playwright install --with-deps chromium" in text
    assert "Runtime visual verify" in text
    assert "node scripts/verify_site_visual_runtime.mjs" in text
    assert "--skip-build" in text
    assert "Upload runtime visual artifacts" in text
    assert "actions/upload-artifact@v4" in text
    assert "if: always() && steps.visualproof.outputs.ui_changed == 'true'" in text


def test_robustness_gates_has_explicit_ruff_install_and_full_matrix_barrier() -> None:
    text = _read(".github/workflows/robustness-gates.yml")
    assert "python -m pip install pytest pytest-asyncio pytest-aiohttp ruff" in text
    assert "Workboard claims gate" in text
    assert "python scripts/check_workboard_claims.py" in text
    assert "Workboard agent accountability gate" in text
    assert "scripts/check_workboard_agent_claim.py" in text
    assert "Workboard issue tooling smoke" in text
    assert "python scripts/workboard_issue.py --help" in text
    assert "full-test-matrix:" in text
    assert "required-gates:" in text
    assert "needs: [protocol-parity, codebase-auto-checks, security-regression, full-test-matrix, docker-smoke]" in text
    assert "python -m pytest -q tests/test_release_hygiene.py" in text
    assert "python -m pytest -q tests/test_mutating_route_policy_exceptions.py" in text
    assert "python -m pytest -q tests/test_check_onboarding_outcomes_gate_script.py" in text
    assert "python -m pytest -q tests/test_dev_artifact_tracking_guard.py" in text
    assert "python -m pytest -q tests/test_check_workboard_claims_gate.py" in text
    assert "python -m pytest -q tests/test_workboard_claim_script.py" in text
    assert "python -m pytest -q tests/test_check_workboard_agent_claim_gate.py" in text
    assert "python -m pytest -q tests/test_agent_bootstrap_claim_script.py" in text
    assert "python -m pytest -q tests/test_workboard_issue_script.py" in text
    assert "python -m pytest -q tests/test_models_cli_subprocess_smoke.py" in text
    assert "python scripts/check_onboarding_outcomes_gate.py --days 7 --json --strict --ignore-low-sample-warning" in text
    assert "python scripts/check_mutating_route_policy_exceptions.py --json --strict" in text


def test_nightly_reliability_workflow_runs_schedule_and_uploads_artifacts() -> None:
    text = _read(".github/workflows/nightly-reliability.yml")
    assert re.search(r"(?m)^on:\s*$", text)
    assert "schedule:" in text
    assert "workflow_dispatch:" in text
    assert 'cron: "15 09 * * *"' in text
    assert "scripts/soak_runner.py" in text
    assert "--failure-command 'python -c \"import sys; sys.exit(1)\"'" in text
    assert "scripts/perf_probe.py" in text
    assert "scripts/check_onboarding_outcomes_gate.py --days 7 --json --strict --ignore-low-sample-warning" in text
    assert "scripts/check_workboard_claims.py --json > artifacts/nightly_reliability/workboard_claims_gate.json" in text
    assert "scripts/workboard_issue.py --help > artifacts/nightly_reliability/workboard_issue_tool_help.txt" in text
    assert "scripts/security_audit.py --repo-root . --json" in text
    assert "actions/upload-artifact@v4" in text
    assert "if: always()" in text


def test_pre_commit_includes_workboard_claims_gate_hook() -> None:
    text = _read(".pre-commit-config.yaml")
    assert "id: thomas-active-folder-guard" in text
    assert (
        "entry: python scripts/active_folders.py guard-staged --auto-claim-staged --require-explicit-agent"
        in text
    )
    assert "id: thomas-workboard-claims-gate" in text
    assert "name: Thomas Workboard Claims Gate" in text
    assert "entry: python scripts/check_workboard_claims.py" in text
    assert "id: thomas-workboard-agent-claim-gate" in text
    assert "name: Thomas Workboard Agent Claim Gate" in text
    assert "entry: python scripts/check_workboard_agent_claim.py" in text
    assert "id: thomas-workboard-issue-tool-smoke" in text
    assert "name: Thomas Workboard Issue Tool Smoke" in text
    assert "entry: python scripts/workboard_issue.py --help" in text
