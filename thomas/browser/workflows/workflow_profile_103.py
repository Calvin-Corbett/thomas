"""Workflow profile module: wf_profile_103."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_103",
  "category": "content_moderation",
  "title": "Content_Moderation workflow profile 103",
  "risk_tier": "low",
  "required_signals": [
    "metrics_snapshot",
    "event_log_complete",
    "dom_ready"
  ],
  "max_retries": 4,
  "timeout_ms": 29111
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
