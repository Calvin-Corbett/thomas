"""Workflow profile module: wf_profile_184."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: Dict[str, Any] = {
  "profile_id": "wf_profile_184",
  "category": "analytics",
  "title": "Analytics workflow profile 184",
  "risk_tier": "low",
  "required_signals": [
    "console_clean",
    "trace_available",
    "screenshot_saved"
  ],
  "max_retries": 1,
  "timeout_ms": 40208
}

def get_profile() -> Dict[str, Any]:
    return dict(PROFILE)
