"""Workflow profile module: wf_profile_048."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
    "profile_id": "wf_profile_048",
    "category": "risk",
    "title": "Risk workflow profile 048",
    "risk_tier": "high",
    "required_signals": ["event_log_complete", "dom_ready", "network_idle"],
    "max_retries": 1,
    "timeout_ms": 21576,
}


def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
