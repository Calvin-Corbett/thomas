"""Workflow profile module: wf_profile_096."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: Dict[str, Any] = {
  "profile_id": "wf_profile_096",
  "category": "content",
  "title": "Content workflow profile 096",
  "risk_tier": "high",
  "required_signals": [
    "metrics_snapshot",
    "event_log_complete",
    "dom_ready"
  ],
  "max_retries": 1,
  "timeout_ms": 28152
}

def get_profile() -> Dict[str, Any]:
    return dict(PROFILE)
