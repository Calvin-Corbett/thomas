"""Workflow profile module: wf_profile_143."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_143",
  "category": "growth",
  "title": "Growth workflow profile 143",
  "risk_tier": "medium",
  "required_signals": [
    "trace_available",
    "screenshot_saved",
    "metrics_snapshot"
  ],
  "max_retries": 4,
  "timeout_ms": 34591
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
