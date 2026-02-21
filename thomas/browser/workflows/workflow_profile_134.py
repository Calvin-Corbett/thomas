"""Workflow profile module: wf_profile_134."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: Dict[str, Any] = {
  "profile_id": "wf_profile_134",
  "category": "profile",
  "title": "Profile workflow profile 134",
  "risk_tier": "medium",
  "required_signals": [
    "network_idle",
    "console_clean",
    "trace_available"
  ],
  "max_retries": 3,
  "timeout_ms": 33358
}

def get_profile() -> Dict[str, Any]:
    return dict(PROFILE)
