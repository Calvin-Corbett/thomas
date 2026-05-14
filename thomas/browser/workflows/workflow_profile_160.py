"""Workflow profile module: wf_profile_160."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_160",
  "category": "release_validation",
  "title": "Release_Validation workflow profile 160",
  "risk_tier": "low",
  "required_signals": [
    "event_log_complete",
    "dom_ready",
    "network_idle"
  ],
  "max_retries": 1,
  "timeout_ms": 36920
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
