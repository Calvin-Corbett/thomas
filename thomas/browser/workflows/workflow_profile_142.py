"""Workflow profile module: wf_profile_142."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
    "profile_id": "wf_profile_142",
    "category": "release_validation",
    "title": "Release_Validation workflow profile 142",
    "risk_tier": "low",
    "required_signals": ["console_clean", "trace_available", "screenshot_saved"],
    "max_retries": 3,
    "timeout_ms": 34454,
}


def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
