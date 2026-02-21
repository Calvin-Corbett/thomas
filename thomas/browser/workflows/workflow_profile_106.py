"""Workflow profile module: wf_profile_106."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: Dict[str, Any] = {
  "profile_id": "wf_profile_106",
  "category": "release_validation",
  "title": "Release_Validation workflow profile 106",
  "risk_tier": "low",
  "required_signals": [
    "network_idle",
    "console_clean",
    "trace_available"
  ],
  "max_retries": 3,
  "timeout_ms": 29522
}

def get_profile() -> Dict[str, Any]:
    return dict(PROFILE)
