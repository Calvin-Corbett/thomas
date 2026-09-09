"""Workflow profile module: wf_profile_036."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
    "profile_id": "wf_profile_036",
    "category": "retention",
    "title": "Retention workflow profile 036",
    "risk_tier": "high",
    "required_signals": ["network_idle", "console_clean", "trace_available"],
    "max_retries": 1,
    "timeout_ms": 19932,
}


def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
