"""Workflow profile module: wf_profile_123."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
    "profile_id": "wf_profile_123",
    "category": "onboarding",
    "title": "Onboarding workflow profile 123",
    "risk_tier": "high",
    "required_signals": ["screenshot_saved", "metrics_snapshot", "event_log_complete"],
    "max_retries": 4,
    "timeout_ms": 31851,
}


def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
