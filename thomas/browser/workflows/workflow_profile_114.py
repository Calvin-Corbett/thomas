"""Workflow profile module: wf_profile_114."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
    "profile_id": "wf_profile_114",
    "category": "content",
    "title": "Content workflow profile 114",
    "risk_tier": "high",
    "required_signals": ["console_clean", "trace_available", "screenshot_saved"],
    "max_retries": 3,
    "timeout_ms": 30618,
}


def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
