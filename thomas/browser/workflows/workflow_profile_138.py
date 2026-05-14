"""Workflow profile module: wf_profile_138."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_138",
  "category": "risk",
  "title": "Risk workflow profile 138",
  "risk_tier": "high",
  "required_signals": [
    "metrics_snapshot",
    "event_log_complete",
    "dom_ready"
  ],
  "max_retries": 3,
  "timeout_ms": 33906
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
