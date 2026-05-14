"""Workflow profile module: wf_profile_003."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_003",
  "category": "support",
  "title": "Support workflow profile 003",
  "risk_tier": "high",
  "required_signals": [
    "trace_available",
    "screenshot_saved",
    "metrics_snapshot"
  ],
  "max_retries": 4,
  "timeout_ms": 15411
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
