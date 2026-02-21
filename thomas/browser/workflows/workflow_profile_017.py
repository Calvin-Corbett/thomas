"""Workflow profile module: wf_profile_017."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: Dict[str, Any] = {
  "profile_id": "wf_profile_017",
  "category": "growth",
  "title": "Growth workflow profile 017",
  "risk_tier": "medium",
  "required_signals": [
    "trace_available",
    "screenshot_saved",
    "metrics_snapshot"
  ],
  "max_retries": 2,
  "timeout_ms": 17329
}

def get_profile() -> Dict[str, Any]:
    return dict(PROFILE)
