"""Workflow profile module: wf_profile_018."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_018",
  "category": "retention",
  "title": "Retention workflow profile 018",
  "risk_tier": "high",
  "required_signals": [
    "screenshot_saved",
    "metrics_snapshot",
    "event_log_complete"
  ],
  "max_retries": 3,
  "timeout_ms": 17466
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
