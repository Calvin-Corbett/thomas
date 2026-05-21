"""Workflow profile module: wf_profile_135."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
    "profile_id": "wf_profile_135",
    "category": "messaging",
    "title": "Messaging workflow profile 135",
    "risk_tier": "high",
    "required_signals": ["console_clean", "trace_available", "screenshot_saved"],
    "max_retries": 4,
    "timeout_ms": 33495,
}


def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
