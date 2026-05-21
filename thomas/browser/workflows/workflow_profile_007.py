"""Workflow profile module: wf_profile_007."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
    "profile_id": "wf_profile_007",
    "category": "search",
    "title": "Search workflow profile 007",
    "risk_tier": "low",
    "required_signals": ["dom_ready", "network_idle", "console_clean"],
    "max_retries": 4,
    "timeout_ms": 15959,
}


def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
