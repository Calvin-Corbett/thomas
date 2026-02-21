"""Workflow profile module: wf_profile_012."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: Dict[str, Any] = {
  "profile_id": "wf_profile_012",
  "category": "risk",
  "title": "Risk workflow profile 012",
  "risk_tier": "high",
  "required_signals": [
    "metrics_snapshot",
    "event_log_complete",
    "dom_ready"
  ],
  "max_retries": 1,
  "timeout_ms": 16644
}

def get_profile() -> Dict[str, Any]:
    return dict(PROFILE)
