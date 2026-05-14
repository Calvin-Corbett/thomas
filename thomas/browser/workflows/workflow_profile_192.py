"""Workflow profile module: wf_profile_192."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_192",
  "category": "risk",
  "title": "Risk workflow profile 192",
  "risk_tier": "high",
  "required_signals": [
    "trace_available",
    "screenshot_saved",
    "metrics_snapshot"
  ],
  "max_retries": 1,
  "timeout_ms": 41304
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
