"""Workflow profile module: wf_profile_049."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_049",
  "category": "content_moderation",
  "title": "Content_Moderation workflow profile 049",
  "risk_tier": "low",
  "required_signals": [
    "dom_ready",
    "network_idle",
    "console_clean"
  ],
  "max_retries": 2,
  "timeout_ms": 21713
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
