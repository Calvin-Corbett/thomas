"""Workflow profile module: wf_profile_100."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: Dict[str, Any] = {
  "profile_id": "wf_profile_100",
  "category": "compliance",
  "title": "Compliance workflow profile 100",
  "risk_tier": "low",
  "required_signals": [
    "console_clean",
    "trace_available",
    "screenshot_saved"
  ],
  "max_retries": 1,
  "timeout_ms": 28700
}

def get_profile() -> Dict[str, Any]:
    return dict(PROFILE)
