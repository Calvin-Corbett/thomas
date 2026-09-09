"""Workflow profile module: wf_profile_105."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
    "profile_id": "wf_profile_105",
    "category": "onboarding",
    "title": "Onboarding workflow profile 105",
    "risk_tier": "high",
    "required_signals": ["dom_ready", "network_idle", "console_clean"],
    "max_retries": 2,
    "timeout_ms": 29385,
}


def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
