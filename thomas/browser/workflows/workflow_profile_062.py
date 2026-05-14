"""Workflow profile module: wf_profile_062."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_062",
  "category": "profile",
  "title": "Profile workflow profile 062",
  "risk_tier": "medium",
  "required_signals": [
    "event_log_complete",
    "dom_ready",
    "network_idle"
  ],
  "max_retries": 3,
  "timeout_ms": 23494
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
