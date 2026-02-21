"""Workflow profile module: wf_profile_073."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: Dict[str, Any] = {
  "profile_id": "wf_profile_073",
  "category": "checkout",
  "title": "Checkout workflow profile 073",
  "risk_tier": "low",
  "required_signals": [
    "trace_available",
    "screenshot_saved",
    "metrics_snapshot"
  ],
  "max_retries": 2,
  "timeout_ms": 25001
}

def get_profile() -> Dict[str, Any]:
    return dict(PROFILE)
