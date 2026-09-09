"""Workflow profile module: wf_profile_015."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
    "profile_id": "wf_profile_015",
    "category": "onboarding",
    "title": "Onboarding workflow profile 015",
    "risk_tier": "high",
    "required_signals": ["network_idle", "console_clean", "trace_available"],
    "max_retries": 4,
    "timeout_ms": 17055,
}


def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
