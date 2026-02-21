"""Workflow profile module: wf_profile_167."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: Dict[str, Any] = {
  "profile_id": "wf_profile_167",
  "category": "admin",
  "title": "Admin workflow profile 167",
  "risk_tier": "medium",
  "required_signals": [
    "event_log_complete",
    "dom_ready",
    "network_idle"
  ],
  "max_retries": 4,
  "timeout_ms": 37879
}

def get_profile() -> Dict[str, Any]:
    return dict(PROFILE)
