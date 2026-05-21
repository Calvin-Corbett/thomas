"""Workflow profile module: wf_profile_001."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
    "profile_id": "wf_profile_001",
    "category": "checkout",
    "title": "Checkout workflow profile 001",
    "risk_tier": "low",
    "required_signals": ["network_idle", "console_clean", "trace_available"],
    "max_retries": 2,
    "timeout_ms": 15137,
}


def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
