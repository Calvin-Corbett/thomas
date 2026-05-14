"""Workflow profile module: wf_profile_178."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_178",
  "category": "release_validation",
  "title": "Release_Validation workflow profile 178",
  "risk_tier": "low",
  "required_signals": [
    "trace_available",
    "screenshot_saved",
    "metrics_snapshot"
  ],
  "max_retries": 3,
  "timeout_ms": 39386
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
