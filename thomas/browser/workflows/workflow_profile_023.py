"""Workflow profile module: wf_profile_023."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
    "profile_id": "wf_profile_023",
    "category": "admin",
    "title": "Admin workflow profile 023",
    "risk_tier": "medium",
    "required_signals": ["console_clean", "trace_available", "screenshot_saved"],
    "max_retries": 4,
    "timeout_ms": 18151,
}


def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
