"""Workflow profile module: wf_profile_020."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
    "profile_id": "wf_profile_020",
    "category": "auth",
    "title": "Auth workflow profile 020",
    "risk_tier": "medium",
    "required_signals": ["event_log_complete", "dom_ready", "network_idle"],
    "max_retries": 1,
    "timeout_ms": 17740,
}


def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
