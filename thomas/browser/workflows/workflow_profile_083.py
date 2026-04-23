"""Workflow profile module: wf_profile_083."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: Dict[str, Any] = {
  "profile_id": "wf_profile_083",
  "category": "payments",
  "title": "Payments workflow profile 083",
  "risk_tier": "medium",
  "required_signals": [
    "event_log_complete",
    "dom_ready",
    "network_idle"
  ],
  "max_retries": 4,
  "timeout_ms": 26371
}

def get_profile() -> Dict[str, Any]:
    return dict(PROFILE)
