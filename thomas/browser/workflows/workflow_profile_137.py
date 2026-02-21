"""Workflow profile module: wf_profile_137."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: Dict[str, Any] = {
  "profile_id": "wf_profile_137",
  "category": "payments",
  "title": "Payments workflow profile 137",
  "risk_tier": "medium",
  "required_signals": [
    "screenshot_saved",
    "metrics_snapshot",
    "event_log_complete"
  ],
  "max_retries": 2,
  "timeout_ms": 33769
}

def get_profile() -> Dict[str, Any]:
    return dict(PROFILE)
