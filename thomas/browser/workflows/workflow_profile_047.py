"""Workflow profile module: wf_profile_047."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_047",
  "category": "payments",
  "title": "Payments workflow profile 047",
  "risk_tier": "medium",
  "required_signals": [
    "metrics_snapshot",
    "event_log_complete",
    "dom_ready"
  ],
  "max_retries": 4,
  "timeout_ms": 21439
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
