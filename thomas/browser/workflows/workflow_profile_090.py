"""Workflow profile module: wf_profile_090."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
    "profile_id": "wf_profile_090",
    "category": "retention",
    "title": "Retention workflow profile 090",
    "risk_tier": "high",
    "required_signals": ["event_log_complete", "dom_ready", "network_idle"],
    "max_retries": 3,
    "timeout_ms": 27330,
}


def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
