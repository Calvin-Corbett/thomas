"""Workflow profile module: wf_profile_182."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: Dict[str, Any] = {
  "profile_id": "wf_profile_182",
  "category": "auth",
  "title": "Auth workflow profile 182",
  "risk_tier": "medium",
  "required_signals": [
    "dom_ready",
    "network_idle",
    "console_clean"
  ],
  "max_retries": 3,
  "timeout_ms": 39934
}

def get_profile() -> Dict[str, Any]:
    return dict(PROFILE)
