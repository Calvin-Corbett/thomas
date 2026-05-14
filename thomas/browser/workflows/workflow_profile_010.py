"""Workflow profile module: wf_profile_010."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_010",
  "category": "compliance",
  "title": "Compliance workflow profile 010",
  "risk_tier": "low",
  "required_signals": [
    "trace_available",
    "screenshot_saved",
    "metrics_snapshot"
  ],
  "max_retries": 3,
  "timeout_ms": 16370
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
