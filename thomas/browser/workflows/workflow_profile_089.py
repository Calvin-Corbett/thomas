"""Workflow profile module: wf_profile_089."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: Dict[str, Any] = {
  "profile_id": "wf_profile_089",
  "category": "growth",
  "title": "Growth workflow profile 089",
  "risk_tier": "medium",
  "required_signals": [
    "metrics_snapshot",
    "event_log_complete",
    "dom_ready"
  ],
  "max_retries": 2,
  "timeout_ms": 27193
}

def get_profile() -> Dict[str, Any]:
    return dict(PROFILE)
