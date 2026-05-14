"""Workflow profile module: wf_profile_121."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_121",
  "category": "content_moderation",
  "title": "Content_Moderation workflow profile 121",
  "risk_tier": "low",
  "required_signals": [
    "console_clean",
    "trace_available",
    "screenshot_saved"
  ],
  "max_retries": 2,
  "timeout_ms": 31577
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
