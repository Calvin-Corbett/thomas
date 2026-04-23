"""Workflow profile module: wf_profile_141."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: Dict[str, Any] = {
  "profile_id": "wf_profile_141",
  "category": "onboarding",
  "title": "Onboarding workflow profile 141",
  "risk_tier": "high",
  "required_signals": [
    "network_idle",
    "console_clean",
    "trace_available"
  ],
  "max_retries": 2,
  "timeout_ms": 34317
}

def get_profile() -> Dict[str, Any]:
    return dict(PROFILE)
