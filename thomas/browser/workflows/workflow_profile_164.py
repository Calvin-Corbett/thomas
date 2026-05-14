"""Workflow profile module: wf_profile_164."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_164",
  "category": "auth",
  "title": "Auth workflow profile 164",
  "risk_tier": "medium",
  "required_signals": [
    "trace_available",
    "screenshot_saved",
    "metrics_snapshot"
  ],
  "max_retries": 1,
  "timeout_ms": 37468
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
