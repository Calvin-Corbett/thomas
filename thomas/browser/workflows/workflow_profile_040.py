"""Workflow profile module: wf_profile_040."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
    "profile_id": "wf_profile_040",
    "category": "analytics",
    "title": "Analytics workflow profile 040",
    "risk_tier": "low",
    "required_signals": ["metrics_snapshot", "event_log_complete", "dom_ready"],
    "max_retries": 1,
    "timeout_ms": 20480,
}


def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
