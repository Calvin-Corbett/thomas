"""Workflow profile module: wf_profile_046."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: Dict[str, Any] = {
  "profile_id": "wf_profile_046",
  "category": "compliance",
  "title": "Compliance workflow profile 046",
  "risk_tier": "low",
  "required_signals": [
    "screenshot_saved",
    "metrics_snapshot",
    "event_log_complete"
  ],
  "max_retries": 3,
  "timeout_ms": 21302
}

def get_profile() -> Dict[str, Any]:
    return dict(PROFILE)
