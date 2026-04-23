"""Workflow profile module: wf_profile_165."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: Dict[str, Any] = {
  "profile_id": "wf_profile_165",
  "category": "support",
  "title": "Support workflow profile 165",
  "risk_tier": "high",
  "required_signals": [
    "screenshot_saved",
    "metrics_snapshot",
    "event_log_complete"
  ],
  "max_retries": 2,
  "timeout_ms": 37605
}

def get_profile() -> Dict[str, Any]:
    return dict(PROFILE)
