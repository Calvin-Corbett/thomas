"""Workflow profile module: wf_profile_024."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_024",
  "category": "content",
  "title": "Content workflow profile 024",
  "risk_tier": "high",
  "required_signals": [
    "trace_available",
    "screenshot_saved",
    "metrics_snapshot"
  ],
  "max_retries": 1,
  "timeout_ms": 18288
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
