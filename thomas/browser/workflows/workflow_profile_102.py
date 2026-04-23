"""Workflow profile module: wf_profile_102."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: Dict[str, Any] = {
  "profile_id": "wf_profile_102",
  "category": "risk",
  "title": "Risk workflow profile 102",
  "risk_tier": "high",
  "required_signals": [
    "screenshot_saved",
    "metrics_snapshot",
    "event_log_complete"
  ],
  "max_retries": 3,
  "timeout_ms": 28974
}

def get_profile() -> Dict[str, Any]:
    return dict(PROFILE)
