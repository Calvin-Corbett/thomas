"""Workflow profile module: wf_profile_038."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_038",
  "category": "auth",
  "title": "Auth workflow profile 038",
  "risk_tier": "medium",
  "required_signals": [
    "trace_available",
    "screenshot_saved",
    "metrics_snapshot"
  ],
  "max_retries": 3,
  "timeout_ms": 20206
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
