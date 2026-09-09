"""Workflow profile module: wf_profile_173."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
    "profile_id": "wf_profile_173",
    "category": "payments",
    "title": "Payments workflow profile 173",
    "risk_tier": "medium",
    "required_signals": ["metrics_snapshot", "event_log_complete", "dom_ready"],
    "max_retries": 2,
    "timeout_ms": 38701,
}


def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
