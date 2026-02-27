"""Gate helpers for onboarding outcomes telemetry quality and KPI thresholds."""

from __future__ import annotations

from typing import Any

from thomas.observability.onboarding_outcomes import get_outcomes_report

REQUIRED_TOP_LEVEL_KEYS = (
    "ok",
    "window_days",
    "summary",
    "stage_counts",
    "event_counts",
    "top_failures",
    "top_failure_reasons",
)

REQUIRED_SUMMARY_KEYS = (
    "events",
    "runs",
    "unique_users",
    "wizard_opened",
    "onboarding_completed",
    "completion_rate",
    "recovery_attempts",
    "recovery_succeeded",
    "recovery_success_rate",
    "completed_journeys_with_timing",
    "median_time_to_ready_seconds",
)


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def evaluate_onboarding_outcomes_gate(
    report: dict[str, Any],
    *,
    min_events_for_quality_thresholds: int = 20,
    min_completion_rate: float = 0.9,
    min_recovery_success_rate: float = 0.8,
    max_median_time_to_ready_seconds: float = 480.0,
) -> dict[str, Any]:
    """Evaluate onboarding report contract + KPI thresholds.

    Contract checks always apply.
    KPI thresholds apply only when enough telemetry events are present.
    """
    errors: list[str] = []
    warnings: list[str] = []

    payload = dict(report or {})

    for key in REQUIRED_TOP_LEVEL_KEYS:
        if key not in payload:
            errors.append(f"missing top-level key: {key}")

    summary_raw = payload.get("summary")
    summary = summary_raw if isinstance(summary_raw, dict) else {}
    if not isinstance(summary_raw, dict):
        errors.append("summary must be an object")

    for key in REQUIRED_SUMMARY_KEYS:
        if key not in summary:
            errors.append(f"missing summary key: {key}")

    events = _int(summary.get("events"), 0)
    opened = _int(summary.get("wizard_opened"), 0)
    completion_rate = _float(summary.get("completion_rate"), 0.0)
    recovery_attempts = _int(summary.get("recovery_attempts"), 0)
    recovery_success_rate = _float(summary.get("recovery_success_rate"), 0.0)
    completed_with_timing = _int(summary.get("completed_journeys_with_timing"), 0)
    median_time_to_ready_seconds = _float(summary.get("median_time_to_ready_seconds"), 0.0)

    min_events = max(0, int(min_events_for_quality_thresholds))
    if events < min_events:
        warnings.append(
            "insufficient onboarding telemetry sample for KPI threshold checks: "
            f"events={events}, required>={min_events}"
        )
    else:
        if opened > 0 and completion_rate < float(min_completion_rate):
            errors.append(
                "onboarding completion rate below target: "
                f"completion_rate={completion_rate:.4f}, target>={float(min_completion_rate):.4f}"
            )
        if recovery_attempts > 0 and recovery_success_rate < float(min_recovery_success_rate):
            errors.append(
                "onboarding recovery success rate below target: "
                f"recovery_success_rate={recovery_success_rate:.4f}, "
                f"target>={float(min_recovery_success_rate):.4f}"
            )
        if completed_with_timing > 0 and median_time_to_ready_seconds > float(max_median_time_to_ready_seconds):
            errors.append(
                "onboarding median time-to-ready above target: "
                f"median_time_to_ready_seconds={median_time_to_ready_seconds:.3f}, "
                f"target<={float(max_median_time_to_ready_seconds):.3f}"
            )
        elif opened > 0 and _int(summary.get("onboarding_completed"), 0) > 0 and completed_with_timing == 0:
            warnings.append("onboarding timing data missing for completed journeys")

    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "events": events,
            "wizard_opened": opened,
            "completion_rate": completion_rate,
            "recovery_attempts": recovery_attempts,
            "recovery_success_rate": recovery_success_rate,
            "completed_journeys_with_timing": completed_with_timing,
            "median_time_to_ready_seconds": median_time_to_ready_seconds,
        },
        "thresholds": {
            "min_events_for_quality_thresholds": min_events,
            "min_completion_rate": float(min_completion_rate),
            "min_recovery_success_rate": float(min_recovery_success_rate),
            "max_median_time_to_ready_seconds": float(max_median_time_to_ready_seconds),
        },
    }


def get_gate_status(
    *,
    since_days: int = 7,
    min_events_for_quality_thresholds: int = 20,
    min_completion_rate: float = 0.9,
    min_recovery_success_rate: float = 0.8,
    max_median_time_to_ready_seconds: float = 480.0,
) -> dict[str, Any]:
    """Backward-compatible helper used by HTTP endpoints."""
    report = get_outcomes_report(since_days=max(1, int(since_days)))
    gate = evaluate_onboarding_outcomes_gate(
        report,
        min_events_for_quality_thresholds=max(0, int(min_events_for_quality_thresholds)),
        min_completion_rate=max(0.0, min(1.0, float(min_completion_rate))),
        min_recovery_success_rate=max(0.0, min(1.0, float(min_recovery_success_rate))),
        max_median_time_to_ready_seconds=max(1.0, float(max_median_time_to_ready_seconds)),
    )
    return {
        "ok": bool(gate.get("ok", False)),
        "gate": gate,
        "onboarding_summary": dict(report.get("summary") or {}),
    }
