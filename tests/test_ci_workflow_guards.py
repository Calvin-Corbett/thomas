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
    assert '--base "${{ steps.diff.outputs.base }}"' in text
    assert '--head "${{ steps.diff.outputs.head }}"' in text
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
    assert "python scripts/check_workboard_claims.py --require-identity-metadata" in text
    assert "Workboard changed-file ownership gate" in text
    assert (
        'python scripts/check_workboard_changed_files.py --base "${BASE_SHA}" --head "${HEAD_SHA}" --require-identity-metadata'
        in text
    )
    assert "Workboard agent accountability gate" in text
    assert "scripts/check_workboard_agent_claim.py" in text
    assert "--enforce-parent-throughput" in text
    assert "--parent-target-workers" in text
    assert "--parent-min-ready-suggestions" in text
    assert "Workboard claim freshness gate" in text
    assert "python scripts/check_workboard_claim_freshness.py --max-age-hours 72" in text
    assert "Workboard issue tooling smoke" in text
    assert "python scripts/workboard_issue.py --help" in text
    assert "Workboard audit backstop gate" in text
    assert "python scripts/workboard_audit_backstop.py" in text
    assert "Competitor freshness guard" in text
    assert "python scripts/check_competitor_freshness_guard.py --max-age-days 7" in text
    assert "full-test-matrix:" in text
    assert "required-gates:" in text
    assert "needs: [protocol-parity, codebase-auto-checks, security-regression, full-test-matrix, docker-smoke]" in text
    assert "python -m pytest -q tests/test_release_hygiene.py" in text
    assert "python -m pytest -q tests/test_mutating_route_policy_exceptions.py" in text
    assert "python -m pytest -q tests/test_check_onboarding_outcomes_gate_script.py" in text
    assert "python -m pytest -q tests/test_dev_artifact_tracking_guard.py" in text
    assert "python -m pytest -q tests/test_check_workboard_claims_gate.py" in text
    assert "python -m pytest -q tests/test_check_workboard_changed_files_gate.py" in text
    assert "python -m pytest -q tests/test_check_workboard_claim_freshness.py" in text
    assert "python -m pytest -q tests/test_workboard_claim_script.py" in text
    assert "python -m pytest -q tests/test_check_workboard_agent_claim_gate.py" in text
    assert "python -m pytest -q tests/test_agent_bootstrap_claim_script.py" in text
    assert "python -m pytest -q tests/test_workboard_issue_script.py" in text
    assert "python -m pytest -q tests/test_workboard_audit_backstop_script.py" in text
    assert "python -m pytest -q tests/test_module_audit_registry.py" in text
    assert "python -m pytest -q tests/test_check_module_audit_gate_script.py" in text
    assert "python -m pytest -q tests/test_record_module_audit_script.py" in text
    assert "python -m pytest -q tests/test_module_audit_status_script.py" in text
    assert "python -m pytest -q tests/test_module_audit_sweep_script.py" in text
    assert "python -m pytest -q tests/test_competitor_freshness_guard.py" in text
    assert "python -m pytest -q tests/test_models_cli_subprocess_smoke.py" in text
    assert (
        "python scripts/check_onboarding_outcomes_gate.py --days 7 --json --strict --ignore-low-sample-warning" in text
    )
    assert "python scripts/check_mutating_route_policy_exceptions.py --json --strict" in text
    assert "python scripts/module_audit_status.py --max-age-hours 24 --json" in text


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
    assert (
        "scripts/check_workboard_claims.py --require-identity-metadata --json > artifacts/nightly_reliability/workboard_claims_gate.json"
        in text
    )
    assert (
        "scripts/check_workboard_changed_files.py --base HEAD~1 --head HEAD --require-identity-metadata --json > artifacts/nightly_reliability/workboard_changed_files_gate.json"
        in text
    )
    assert (
        "scripts/workboard_audit_backstop.py --json > artifacts/nightly_reliability/workboard_audit_backstop.json"
        in text
    )
    assert (
        "scripts/workboard_claim_cleanup.py --max-age-hours 72 --json > artifacts/nightly_reliability/workboard_claim_cleanup.json"
        in text
    )
    assert (
        "scripts/check_competitor_freshness_guard.py --max-age-days 7 --json > artifacts/nightly_reliability/competitor_freshness_guard.json"
        in text
    )
    assert (
        "scripts/module_audit_status.py --max-age-hours 24 --json > artifacts/nightly_reliability/module_audit_status_24h.json"
        in text
    )
    assert "scripts/workboard_issue.py --help > artifacts/nightly_reliability/workboard_issue_tool_help.txt" in text
    assert "scripts/security_audit.py --repo-root . --json" in text
    assert "actions/upload-artifact@v4" in text
    assert "if: always()" in text


def test_pre_commit_includes_workboard_claims_gate_hook() -> None:
    text = _read(".pre-commit-config.yaml")
    assert "id: thomas-active-folder-guard" in text
    assert "entry: python scripts/active_folders.py guard-staged --auto-claim-staged --require-explicit-agent" in text
    assert "id: thomas-precommit-skip-policy-gate" in text
    assert "name: Thomas Pre-commit Skip Policy Gate" in text
    assert "entry: python scripts/check_precommit_skip_policy.py" in text
    assert "id: thomas-workboard-claims-gate" in text
    assert "name: Thomas Workboard Claims Gate" in text
    assert "entry: python scripts/check_workboard_claims.py --require-identity-metadata" in text
    assert "id: thomas-workboard-task-problems-gate" in text
    assert "name: Thomas Workboard Task Problems Gate" in text
    assert "entry: python scripts/check_workboard_task_problems.py" in text
    assert "id: thomas-workboard-changed-files-gate" in text
    assert "name: Thomas Workboard Changed Files Gate" in text
    assert "entry: python scripts/check_workboard_changed_files.py --staged --require-identity-metadata" in text
    assert "id: thomas-workboard-agent-claim-gate" in text
    assert "name: Thomas Workboard Agent Claim Gate" in text
    assert (
        "entry: python scripts/check_workboard_agent_claim.py --enforce-staged-scope --enforce-parent-throughput --parent-target-workers 2 --parent-min-ready-suggestions 2"
        in text
    )
    assert "id: thomas-workboard-issue-tool-smoke" in text
    assert "name: Thomas Workboard Issue Tool Smoke" in text
    assert "entry: python scripts/workboard_issue.py --help" in text
    assert "id: thomas-workboard-audit-backstop-gate" in text
    assert "name: Thomas Workboard Audit Backstop Gate" in text
    assert "entry: python scripts/workboard_audit_backstop.py" in text
    assert "id: thomas-repo-identity-gate" in text
    assert "name: Thomas Repo Identity Gate" in text
    assert "entry: python scripts/check_repo_identity.py" in text
