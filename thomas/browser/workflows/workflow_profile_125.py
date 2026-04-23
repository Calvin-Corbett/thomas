"""Workflow profile module: wf_profile_125."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: Dict[str, Any] = {
  "profile_id": "wf_profile_125",
  "category": "growth",
  "title": "Growth workflow profile 125",
  "risk_tier": "medium",
  "required_signals": [
    "event_log_complete",
    "dom_ready",
    "network_idle"
  ],
  "max_retries": 2,
  "timeout_ms": 32125
}

def get_profile() -> Dict[str, Any]:
    return dict(PROFILE)
