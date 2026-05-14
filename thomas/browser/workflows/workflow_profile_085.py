"""Workflow profile module: wf_profile_085."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_085",
  "category": "content_moderation",
  "title": "Content_Moderation workflow profile 085",
  "risk_tier": "low",
  "required_signals": [
    "network_idle",
    "console_clean",
    "trace_available"
  ],
  "max_retries": 2,
  "timeout_ms": 26645
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
