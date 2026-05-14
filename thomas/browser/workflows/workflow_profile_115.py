"""Workflow profile module: wf_profile_115."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_115",
  "category": "search",
  "title": "Search workflow profile 115",
  "risk_tier": "low",
  "required_signals": [
    "trace_available",
    "screenshot_saved",
    "metrics_snapshot"
  ],
  "max_retries": 4,
  "timeout_ms": 30755
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
