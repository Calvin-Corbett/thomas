"""Aggregated security audit report for governance and release posture."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from thomas.plugins.certification import certify_extension_catalog
from thomas.security.dependency_policy import evaluate_dependency_policy
from thomas.security.incident_drill import _validate_scoped_path, run_security_incident_drill
from thomas.security.mutating_route_policy import evaluate_mutating_route_policy_exceptions
from thomas.security.threat_model_cadence import evaluate_threat_model_cadence
from thomas.system.release_contracts import build_release_contract_report


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_security_audit(
    repo_root: Path,
    *,
    max_threat_model_age_days: int = 30,
    min_extension_pass_rate: float = 0.95,
    include_incident_drill: bool = False,
) -> dict[str, Any]:
    root = repo_root.resolve()

    checks: dict[str, Any] = {}

    pyproject_path = root / "pyproject.toml"
    if pyproject_path.exists():
        checks["dependency_policy"] = evaluate_dependency_policy(pyproject_path)
    else:
        checks["dependency_policy"] = {
            "ok": False,
            "errors": [
                {
                    "code": "dependency_policy.pyproject_missing",
                    "message": f"pyproject.toml not found at {pyproject_path}",
                    "remediation": "Run this audit at repository root.",
                }
            ],
            "warnings": [],
            "summary": {"error_count": 1, "warning_count": 0},
        }

    threat_model_path = root / "docs" / "THREAT_MODEL_WEB_API.md"
    try:
        threat_model_path = _validate_scoped_path(
            root,
            "docs/THREAT_MODEL_WEB_API.md",
            scope="plan",
        )
    except ValueError as exc:
        checks["threat_model_cadence"] = {
            "ok": False,
            "path": str(threat_model_path),
            "errors": [
                {
                    "code": "threat_model.scope_violation",
                    "message": str(exc),
                    "remediation": "Verify threat-model file path ownership against declared plan scope.",
                }
            ],
            "warnings": [],
            "summary": {"error_count": 1, "warning_count": 0},
        }
    else:
        checks["threat_model_cadence"] = evaluate_threat_model_cadence(
            threat_model_path,
            max_age_days=max_threat_model_age_days,
        )

    checks["mutating_route_policy"] = evaluate_mutating_route_policy_exceptions(root)

    checks["release_contracts"] = build_release_contract_report(root / "docs" / "release" / "contract_registry.json")

    checks["extension_certification"] = certify_extension_catalog(
        root / "extensions",
        min_pass_rate=min_extension_pass_rate,
    )

    if include_incident_drill:
        checks["incident_drill"] = run_security_incident_drill(
            root,
            scenario="security_audit",
            include_command_checks=False,
        )
    else:
        checks["incident_drill"] = {
            "ok": True,
            "skipped": True,
            "summary": {"step_count": 0, "passed": 0, "failed": 0},
            "note": "Incident drill skipped (use --include-incident-drill to run).",
        }

    failing_checks = [name for name, payload in checks.items() if not bool(payload.get("ok", False))]
    warning_count = 0
    error_count = 0
    for payload in checks.values():
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        warning_count += int(summary.get("warning_count") or 0)
        error_count += int(summary.get("error_count") or 0)
        if "failed" in summary:
            error_count += int(summary.get("failed") or 0)

    return {
        "ok": len(failing_checks) == 0,
        "started_at": _now_iso(),
        "repo_root": str(root),
        "summary": {
            "check_count": len(checks),
            "failing_checks": failing_checks,
            "error_count": error_count,
            "warning_count": warning_count,
        },
        "checks": checks,
    }
