"""Workflow profile module: wf_profile_113."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
    "profile_id": "wf_profile_113",
    "category": "admin",
    "title": "Admin workflow profile 113",
    "risk_tier": "medium",
    "required_signals": ["network_idle", "console_clean", "trace_available"],
    "max_retries": 2,
    "timeout_ms": 30481,
}


def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
