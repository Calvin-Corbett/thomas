"""Workflow profile module: wf_profile_108."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_108",
  "category": "retention",
  "title": "Retention workflow profile 108",
  "risk_tier": "high",
  "required_signals": [
    "trace_available",
    "screenshot_saved",
    "metrics_snapshot"
  ],
  "max_retries": 1,
  "timeout_ms": 29796
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
