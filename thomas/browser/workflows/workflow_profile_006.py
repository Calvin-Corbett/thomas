"""Workflow profile module: wf_profile_006."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: Dict[str, Any] = {
  "profile_id": "wf_profile_006",
  "category": "content",
  "title": "Content workflow profile 006",
  "risk_tier": "high",
  "required_signals": [
    "event_log_complete",
    "dom_ready",
    "network_idle"
  ],
  "max_retries": 3,
  "timeout_ms": 15822
}

def get_profile() -> Dict[str, Any]:
    return dict(PROFILE)
