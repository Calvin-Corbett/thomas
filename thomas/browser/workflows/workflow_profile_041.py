"""Workflow profile module: wf_profile_041."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: Dict[str, Any] = {
  "profile_id": "wf_profile_041",
  "category": "admin",
  "title": "Admin workflow profile 041",
  "risk_tier": "medium",
  "required_signals": [
    "event_log_complete",
    "dom_ready",
    "network_idle"
  ],
  "max_retries": 2,
  "timeout_ms": 20617
}

def get_profile() -> Dict[str, Any]:
    return dict(PROFILE)
