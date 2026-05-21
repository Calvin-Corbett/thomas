"""Workflow profile module: wf_profile_171."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
    "profile_id": "wf_profile_171",
    "category": "messaging",
    "title": "Messaging workflow profile 171",
    "risk_tier": "high",
    "required_signals": ["trace_available", "screenshot_saved", "metrics_snapshot"],
    "max_retries": 4,
    "timeout_ms": 38427,
}


def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
