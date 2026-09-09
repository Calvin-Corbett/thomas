"""Workflow profile module: wf_profile_189."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
    "profile_id": "wf_profile_189",
    "category": "messaging",
    "title": "Messaging workflow profile 189",
    "risk_tier": "high",
    "required_signals": ["dom_ready", "network_idle", "console_clean"],
    "max_retries": 2,
    "timeout_ms": 40893,
}


def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
