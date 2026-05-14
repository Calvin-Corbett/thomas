"""Workflow profile module: wf_profile_110."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_110",
  "category": "auth",
  "title": "Auth workflow profile 110",
  "risk_tier": "medium",
  "required_signals": [
    "metrics_snapshot",
    "event_log_complete",
    "dom_ready"
  ],
  "max_retries": 3,
  "timeout_ms": 30070
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
