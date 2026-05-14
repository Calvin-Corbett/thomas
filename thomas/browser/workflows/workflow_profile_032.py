"""Workflow profile module: wf_profile_032."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_032",
  "category": "audit",
  "title": "Audit workflow profile 032",
  "risk_tier": "medium",
  "required_signals": [
    "screenshot_saved",
    "metrics_snapshot",
    "event_log_complete"
  ],
  "max_retries": 1,
  "timeout_ms": 19384
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
