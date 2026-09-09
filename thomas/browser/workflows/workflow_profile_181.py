"""Workflow profile module: wf_profile_181."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
    "profile_id": "wf_profile_181",
    "category": "checkout",
    "title": "Checkout workflow profile 181",
    "risk_tier": "low",
    "required_signals": ["event_log_complete", "dom_ready", "network_idle"],
    "max_retries": 2,
    "timeout_ms": 39797,
}


def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
