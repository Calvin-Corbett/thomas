"""Workflow profile module: wf_profile_144."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_144",
  "category": "retention",
  "title": "Retention workflow profile 144",
  "risk_tier": "high",
  "required_signals": [
    "screenshot_saved",
    "metrics_snapshot",
    "event_log_complete"
  ],
  "max_retries": 1,
  "timeout_ms": 34728
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
