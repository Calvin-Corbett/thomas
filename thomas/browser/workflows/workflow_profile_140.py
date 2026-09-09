"""Workflow profile module: wf_profile_140."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
    "profile_id": "wf_profile_140",
    "category": "audit",
    "title": "Audit workflow profile 140",
    "risk_tier": "medium",
    "required_signals": ["dom_ready", "network_idle", "console_clean"],
    "max_retries": 1,
    "timeout_ms": 34180,
}


def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
