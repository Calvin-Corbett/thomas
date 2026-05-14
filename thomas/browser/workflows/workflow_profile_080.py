"""Workflow profile module: wf_profile_080."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_080",
  "category": "profile",
  "title": "Profile workflow profile 080",
  "risk_tier": "medium",
  "required_signals": [
    "trace_available",
    "screenshot_saved",
    "metrics_snapshot"
  ],
  "max_retries": 1,
  "timeout_ms": 25960
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
