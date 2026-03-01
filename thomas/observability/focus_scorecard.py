"""Telemetry-driven weekly focus scorecard for outcome-based prioritization."""

from __future__ import annotations

from datetime import datetime, timezone
from importlib import import_module
from pathlib import Path
from typing import Any

from thomas.observability.onboarding_outcomes import build_onboarding_outcome_report


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except ImportError:
        return default


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except ImportError:
        return default


def _clamp_score(value: float) -> int:
    num = max(0.0, min(100.0, float(value)))
    return int(round(num))


def _build_priorities(config_report: dict[str, Any], onboarding_report: dict[str, Any]) -> list[dict[str, Any]]:
    priorities: list[dict[str, Any]] = []

    cfg_summary = dict(config_report.get("summary") or {})
    err_count = _int(cfg_summary.get("error_count"), 0)
    warn_count = _int(cfg_summary.get("warning_count"), 0)

    onboarding_summary = dict(onboarding_report.get("summary") or {})
    opened = _int(onboarding_summary.get("wizard_opened"), 0)
    completion_rate = _float(onboarding_summary.get("completion_rate"), 0.0)
    recovery_attempts = _int(onboarding_summary.get("recovery_attempts"), 0)
    recovery_success_rate = _float(onboarding_summary.get("recovery_success_rate"), 0.0)
    top_failures = list(onboarding_report.get("top_failures") or [])

    if err_count > 0:
        priorities.append(
            {
                "id": "cfg_blocking_errors",
                "severity": "critical",
                "lane": "D2_trust_governance_safety",
                "reason": f"Blocking config errors detected ({err_count}).",
                "actions": [
                    "Run `thomas config validate --strict --json` and resolve all errors.",
                    "Re-run setup diagnostics endpoint after fixes.",
                ],
            }
        )

    if opened >= 5 and completion_rate < 0.8:
        priorities.append(
            {
                "id": "onboarding_conversion_drop",
                "severity": "high",
                "lane": "D1_setup_to_success",
                "reason": (f"Onboarding completion below target: {completion_rate:.2%} over {opened} wizard opens."),
                "actions": [
                    "Review onboarding stage drop-offs and top failure events.",
                    "Prioritize UX/recovery fixes for the dominant failing step.",
                ],
            }
        )

    if top_failures:
        lead = dict(top_failures[0] or {})
        priorities.append(
            {
                "id": "repeat_failure_pattern",
                "severity": "high",
                "lane": "D3_reliability",
                "reason": f"Most common onboarding failure event: {lead.get('event', 'unknown')} ({lead.get('count', 0)} hits).",
                "actions": [
                    "Add/adjust recovery flow for this failure class.",
                    "Add regression coverage tied to this failure signature.",
                ],
            }
        )

    if recovery_attempts >= 3 and recovery_success_rate < 0.8:
        priorities.append(
            {
                "id": "recovery_flow_low_success",
                "severity": "high",
                "lane": "D1_setup_to_success",
                "reason": (
                    "Recovery success below target: "
                    f"{recovery_success_rate:.2%} over {recovery_attempts} recovery outcomes."
                ),
                "actions": [
                    "Review setup/repair failures and tighten one-click repair playbooks.",
                    "Add remediation copy/tests for top recovery failure reasons.",
                ],
            }
        )

    if warn_count >= 10:
        priorities.append(
            {
                "id": "config_warning_backlog",
                "severity": "medium",
                "lane": "D2_trust_governance_safety",
                "reason": f"High config warning volume ({warn_count}) may hide real failures.",
                "actions": [
                    "Reduce warning baseline by fixing stale profile/provider configs.",
                    "Document accepted warnings and suppress only with explicit policy.",
                ],
            }
        )

    if not priorities:
        priorities.append(
            {
                "id": "maintain_course",
                "severity": "low",
                "lane": "D1_D2_D3",
                "reason": "No critical regressions detected in current scorecard window.",
                "actions": [
                    "Continue weekly soak/perf/security cadence.",
                    "Drive next sprint by KPI deltas rather than parity backlog.",
                ],
            }
        )

    return priorities


def _compute_health_score(config_report: dict[str, Any], onboarding_report: dict[str, Any]) -> int:
    cfg_summary = dict(config_report.get("summary") or {})
    err_count = _int(cfg_summary.get("error_count"), 0)
    warn_count = _int(cfg_summary.get("warning_count"), 0)

    onboarding_summary = dict(onboarding_report.get("summary") or {})
    opened = _int(onboarding_summary.get("wizard_opened"), 0)
    completion_rate = _float(onboarding_summary.get("completion_rate"), 0.0)
    recovery_attempts = _int(onboarding_summary.get("recovery_attempts"), 0)
    recovery_success_rate = _float(onboarding_summary.get("recovery_success_rate"), 0.0)
    top_failures = list(onboarding_report.get("top_failures") or [])

    score = 100.0
    score -= min(60.0, float(err_count) * 15.0)
    score -= min(25.0, float(warn_count) * 2.0)
    if opened > 0:
        score -= min(30.0, (1.0 - max(0.0, min(1.0, completion_rate))) * 40.0)
    if recovery_attempts > 0:
        score -= min(18.0, (1.0 - max(0.0, min(1.0, recovery_success_rate))) * 24.0)
    if top_failures:
        score -= 8.0
    return _clamp_score(score)


def build_focus_scorecard(
    *,
    runs_db_path: Path,
    config_path: Path | None = None,
    window_days: int = 7,
) -> dict[str, Any]:
    days = max(1, min(90, int(window_days)))
    onboarding_report = build_onboarding_outcome_report(runs_db_path, since_days=days)
    validate_config = getattr(import_module("thomas.system.config_validator"), "validate_config")
    config_report = (
        validate_config(config_path)
        if config_path is not None
        else {
            "ok": True,
            "summary": {"error_count": 0, "warning_count": 0},
            "errors": [],
            "warnings": [],
            "config_path": "",
        }
    )

    health_score = _compute_health_score(config_report, onboarding_report)
    priorities = _build_priorities(config_report, onboarding_report)

    return {
        "ok": True,
        "generated_at": _now_iso(),
        "window_days": days,
        "health_score": int(health_score),
        "lanes": {
            "d1_setup_to_success": "onboarding activation + recovery",
            "d2_trust_governance_safety": "security + policy + authz",
            "d3_reliability": "soak + perf + failure handling",
        },
        "kpis": {
            "config": dict(config_report.get("summary") or {}),
            "onboarding": dict(onboarding_report.get("summary") or {}),
        },
        "priority_actions": priorities,
        "inputs": {
            "runs_db_path": str(runs_db_path),
            "config_path": str(config_report.get("config_path") or ""),
        },
    }
