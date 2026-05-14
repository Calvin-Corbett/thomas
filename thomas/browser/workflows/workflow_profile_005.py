"""Workflow profile module: wf_profile_005."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_005",
  "category": "admin",
  "title": "Admin workflow profile 005",
  "risk_tier": "medium",
  "required_signals": [
    "metrics_snapshot",
    "event_log_complete",
    "dom_ready"
  ],
  "max_retries": 2,
  "timeout_ms": 15685
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
