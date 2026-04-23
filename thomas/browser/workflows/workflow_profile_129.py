"""Workflow profile module: wf_profile_129."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: Dict[str, Any] = {
  "profile_id": "wf_profile_129",
  "category": "support",
  "title": "Support workflow profile 129",
  "risk_tier": "high",
  "required_signals": [
    "trace_available",
    "screenshot_saved",
    "metrics_snapshot"
  ],
  "max_retries": 2,
  "timeout_ms": 32673
}

def get_profile() -> Dict[str, Any]:
    return dict(PROFILE)
