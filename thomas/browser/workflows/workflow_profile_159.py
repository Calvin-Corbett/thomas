"""Workflow profile module: wf_profile_159."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: Dict[str, Any] = {
  "profile_id": "wf_profile_159",
  "category": "onboarding",
  "title": "Onboarding workflow profile 159",
  "risk_tier": "high",
  "required_signals": [
    "metrics_snapshot",
    "event_log_complete",
    "dom_ready"
  ],
  "max_retries": 4,
  "timeout_ms": 36783
}

def get_profile() -> Dict[str, Any]:
    return dict(PROFILE)
