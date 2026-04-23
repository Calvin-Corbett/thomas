"""Workflow profile module: wf_profile_044."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: Dict[str, Any] = {
  "profile_id": "wf_profile_044",
  "category": "profile",
  "title": "Profile workflow profile 044",
  "risk_tier": "medium",
  "required_signals": [
    "console_clean",
    "trace_available",
    "screenshot_saved"
  ],
  "max_retries": 1,
  "timeout_ms": 21028
}

def get_profile() -> Dict[str, Any]:
    return dict(PROFILE)
