"""Workflow profile module: wf_profile_107."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: Dict[str, Any] = {
  "profile_id": "wf_profile_107",
  "category": "growth",
  "title": "Growth workflow profile 107",
  "risk_tier": "medium",
  "required_signals": [
    "console_clean",
    "trace_available",
    "screenshot_saved"
  ],
  "max_retries": 4,
  "timeout_ms": 29659
}

def get_profile() -> Dict[str, Any]:
    return dict(PROFILE)
