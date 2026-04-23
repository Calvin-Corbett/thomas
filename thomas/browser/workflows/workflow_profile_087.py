"""Workflow profile module: wf_profile_087."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: Dict[str, Any] = {
  "profile_id": "wf_profile_087",
  "category": "onboarding",
  "title": "Onboarding workflow profile 087",
  "risk_tier": "high",
  "required_signals": [
    "trace_available",
    "screenshot_saved",
    "metrics_snapshot"
  ],
  "max_retries": 4,
  "timeout_ms": 26919
}

def get_profile() -> Dict[str, Any]:
    return dict(PROFILE)
