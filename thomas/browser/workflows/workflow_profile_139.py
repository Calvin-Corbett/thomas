"""Workflow profile module: wf_profile_139."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: Dict[str, Any] = {
  "profile_id": "wf_profile_139",
  "category": "content_moderation",
  "title": "Content_Moderation workflow profile 139",
  "risk_tier": "low",
  "required_signals": [
    "event_log_complete",
    "dom_ready",
    "network_idle"
  ],
  "max_retries": 4,
  "timeout_ms": 34043
}

def get_profile() -> Dict[str, Any]:
    return dict(PROFILE)
