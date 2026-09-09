"""Workflow profile module: wf_profile_157."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
    "profile_id": "wf_profile_157",
    "category": "content_moderation",
    "title": "Content_Moderation workflow profile 157",
    "risk_tier": "low",
    "required_signals": ["trace_available", "screenshot_saved", "metrics_snapshot"],
    "max_retries": 2,
    "timeout_ms": 36509,
}


def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
