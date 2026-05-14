"""Workflow profile module: wf_profile_033."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_033",
  "category": "onboarding",
  "title": "Onboarding workflow profile 033",
  "risk_tier": "high",
  "required_signals": [
    "metrics_snapshot",
    "event_log_complete",
    "dom_ready"
  ],
  "max_retries": 2,
  "timeout_ms": 19521
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
