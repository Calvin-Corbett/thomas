"""Workflow profile module: wf_profile_025."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_025",
  "category": "search",
  "title": "Search workflow profile 025",
  "risk_tier": "low",
  "required_signals": [
    "screenshot_saved",
    "metrics_snapshot",
    "event_log_complete"
  ],
  "max_retries": 2,
  "timeout_ms": 18425
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
