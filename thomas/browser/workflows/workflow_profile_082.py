"""Workflow profile module: wf_profile_082."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
    "profile_id": "wf_profile_082",
    "category": "compliance",
    "title": "Compliance workflow profile 082",
    "risk_tier": "low",
    "required_signals": ["metrics_snapshot", "event_log_complete", "dom_ready"],
    "max_retries": 3,
    "timeout_ms": 26234,
}


def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
