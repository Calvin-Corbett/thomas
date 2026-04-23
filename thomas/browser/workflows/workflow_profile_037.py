"""Workflow profile module: wf_profile_037."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: Dict[str, Any] = {
  "profile_id": "wf_profile_037",
  "category": "checkout",
  "title": "Checkout workflow profile 037",
  "risk_tier": "low",
  "required_signals": [
    "console_clean",
    "trace_available",
    "screenshot_saved"
  ],
  "max_retries": 2,
  "timeout_ms": 20069
}

def get_profile() -> Dict[str, Any]:
    return dict(PROFILE)
