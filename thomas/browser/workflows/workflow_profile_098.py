"""Workflow profile module: wf_profile_098."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_098",
  "category": "profile",
  "title": "Profile workflow profile 098",
  "risk_tier": "medium",
  "required_signals": [
    "dom_ready",
    "network_idle",
    "console_clean"
  ],
  "max_retries": 3,
  "timeout_ms": 28426
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
