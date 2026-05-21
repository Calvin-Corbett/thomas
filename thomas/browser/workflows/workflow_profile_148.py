"""Workflow profile module: wf_profile_148."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
    "profile_id": "wf_profile_148",
    "category": "analytics",
    "title": "Analytics workflow profile 148",
    "risk_tier": "low",
    "required_signals": ["network_idle", "console_clean", "trace_available"],
    "max_retries": 1,
    "timeout_ms": 35276,
}


def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
