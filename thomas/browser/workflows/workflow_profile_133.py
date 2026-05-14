"""Workflow profile module: wf_profile_133."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_133",
  "category": "search",
  "title": "Search workflow profile 133",
  "risk_tier": "low",
  "required_signals": [
    "dom_ready",
    "network_idle",
    "console_clean"
  ],
  "max_retries": 2,
  "timeout_ms": 33221
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
