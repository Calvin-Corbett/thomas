"""Workflow profile module: wf_profile_076."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_076",
  "category": "analytics",
  "title": "Analytics workflow profile 076",
  "risk_tier": "low",
  "required_signals": [
    "event_log_complete",
    "dom_ready",
    "network_idle"
  ],
  "max_retries": 1,
  "timeout_ms": 25412
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
