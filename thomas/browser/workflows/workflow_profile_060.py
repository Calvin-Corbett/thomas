"""Workflow profile module: wf_profile_060."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: Dict[str, Any] = {
  "profile_id": "wf_profile_060",
  "category": "content",
  "title": "Content workflow profile 060",
  "risk_tier": "high",
  "required_signals": [
    "screenshot_saved",
    "metrics_snapshot",
    "event_log_complete"
  ],
  "max_retries": 1,
  "timeout_ms": 23220
}

def get_profile() -> Dict[str, Any]:
    return dict(PROFILE)
