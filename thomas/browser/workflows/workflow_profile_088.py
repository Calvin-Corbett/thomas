"""Workflow profile module: wf_profile_088."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
    "profile_id": "wf_profile_088",
    "category": "release_validation",
    "title": "Release_Validation workflow profile 088",
    "risk_tier": "low",
    "required_signals": ["screenshot_saved", "metrics_snapshot", "event_log_complete"],
    "max_retries": 1,
    "timeout_ms": 27056,
}


def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
