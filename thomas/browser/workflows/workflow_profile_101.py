"""Workflow profile module: wf_profile_101."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_101",
  "category": "payments",
  "title": "Payments workflow profile 101",
  "risk_tier": "medium",
  "required_signals": [
    "trace_available",
    "screenshot_saved",
    "metrics_snapshot"
  ],
  "max_retries": 2,
  "timeout_ms": 28837
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
