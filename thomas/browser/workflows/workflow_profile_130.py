"""Workflow profile module: wf_profile_130."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
    "profile_id": "wf_profile_130",
    "category": "analytics",
    "title": "Analytics workflow profile 130",
    "risk_tier": "low",
    "required_signals": ["screenshot_saved", "metrics_snapshot", "event_log_complete"],
    "max_retries": 3,
    "timeout_ms": 32810,
}


def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
