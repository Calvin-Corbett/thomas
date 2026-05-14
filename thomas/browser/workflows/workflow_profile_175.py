"""Workflow profile module: wf_profile_175."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_175",
  "category": "content_moderation",
  "title": "Content_Moderation workflow profile 175",
  "risk_tier": "low",
  "required_signals": [
    "dom_ready",
    "network_idle",
    "console_clean"
  ],
  "max_retries": 4,
  "timeout_ms": 38975
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
