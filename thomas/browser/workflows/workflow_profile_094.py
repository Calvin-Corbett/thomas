"""Workflow profile module: wf_profile_094."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_094",
  "category": "analytics",
  "title": "Analytics workflow profile 094",
  "risk_tier": "low",
  "required_signals": [
    "trace_available",
    "screenshot_saved",
    "metrics_snapshot"
  ],
  "max_retries": 3,
  "timeout_ms": 27878
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
