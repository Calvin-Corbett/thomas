"""Workflow profile module: wf_profile_067."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
    "profile_id": "wf_profile_067",
    "category": "content_moderation",
    "title": "Content_Moderation workflow profile 067",
    "risk_tier": "low",
    "required_signals": ["screenshot_saved", "metrics_snapshot", "event_log_complete"],
    "max_retries": 4,
    "timeout_ms": 24179,
}


def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
