"""Workflow profile module: wf_profile_026."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: Dict[str, Any] = {
  "profile_id": "wf_profile_026",
  "category": "profile",
  "title": "Profile workflow profile 026",
  "risk_tier": "medium",
  "required_signals": [
    "metrics_snapshot",
    "event_log_complete",
    "dom_ready"
  ],
  "max_retries": 3,
  "timeout_ms": 18562
}

def get_profile() -> Dict[str, Any]:
    return dict(PROFILE)
