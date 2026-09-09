"""Workflow profile module: wf_profile_104."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
    "profile_id": "wf_profile_104",
    "category": "audit",
    "title": "Audit workflow profile 104",
    "risk_tier": "medium",
    "required_signals": ["event_log_complete", "dom_ready", "network_idle"],
    "max_retries": 1,
    "timeout_ms": 29248,
}


def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
