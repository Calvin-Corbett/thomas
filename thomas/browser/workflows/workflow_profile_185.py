"""Workflow profile module: wf_profile_185."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
    "profile_id": "wf_profile_185",
    "category": "admin",
    "title": "Admin workflow profile 185",
    "risk_tier": "medium",
    "required_signals": ["trace_available", "screenshot_saved", "metrics_snapshot"],
    "max_retries": 2,
    "timeout_ms": 40345,
}


def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
