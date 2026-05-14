"""Workflow profile module: wf_profile_151."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_151",
  "category": "search",
  "title": "Search workflow profile 151",
  "risk_tier": "low",
  "required_signals": [
    "screenshot_saved",
    "metrics_snapshot",
    "event_log_complete"
  ],
  "max_retries": 4,
  "timeout_ms": 35687
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
