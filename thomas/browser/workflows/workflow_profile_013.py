"""Workflow profile module: wf_profile_013."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
    "profile_id": "wf_profile_013",
    "category": "content_moderation",
    "title": "Content_Moderation workflow profile 013",
    "risk_tier": "low",
    "required_signals": ["event_log_complete", "dom_ready", "network_idle"],
    "max_retries": 2,
    "timeout_ms": 16781,
}


def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
