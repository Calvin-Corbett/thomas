"""Workflow profile module: wf_profile_019."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
    "profile_id": "wf_profile_019",
    "category": "checkout",
    "title": "Checkout workflow profile 019",
    "risk_tier": "low",
    "required_signals": ["metrics_snapshot", "event_log_complete", "dom_ready"],
    "max_retries": 4,
    "timeout_ms": 17603,
}


def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
