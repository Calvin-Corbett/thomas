"""Workflow profile module: wf_profile_065."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: Dict[str, Any] = {
  "profile_id": "wf_profile_065",
  "category": "payments",
  "title": "Payments workflow profile 065",
  "risk_tier": "medium",
  "required_signals": [
    "console_clean",
    "trace_available",
    "screenshot_saved"
  ],
  "max_retries": 2,
  "timeout_ms": 23905
}

def get_profile() -> Dict[str, Any]:
    return dict(PROFILE)
