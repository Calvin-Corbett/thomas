"""Workflow profile module: wf_profile_177."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
    "profile_id": "wf_profile_177",
    "category": "onboarding",
    "title": "Onboarding workflow profile 177",
    "risk_tier": "high",
    "required_signals": ["console_clean", "trace_available", "screenshot_saved"],
    "max_retries": 2,
    "timeout_ms": 39249,
}


def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
