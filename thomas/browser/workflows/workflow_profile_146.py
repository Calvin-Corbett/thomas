"""Workflow profile module: wf_profile_146."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_146",
  "category": "auth",
  "title": "Auth workflow profile 146",
  "risk_tier": "medium",
  "required_signals": [
    "event_log_complete",
    "dom_ready",
    "network_idle"
  ],
  "max_retries": 3,
  "timeout_ms": 35002
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
