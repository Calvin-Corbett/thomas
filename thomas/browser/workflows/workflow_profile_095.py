"""Workflow profile module: wf_profile_095."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_095",
  "category": "admin",
  "title": "Admin workflow profile 095",
  "risk_tier": "medium",
  "required_signals": [
    "screenshot_saved",
    "metrics_snapshot",
    "event_log_complete"
  ],
  "max_retries": 4,
  "timeout_ms": 28015
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
