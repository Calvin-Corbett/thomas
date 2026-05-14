"""Workflow profile module: wf_profile_063."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_063",
  "category": "messaging",
  "title": "Messaging workflow profile 063",
  "risk_tier": "high",
  "required_signals": [
    "dom_ready",
    "network_idle",
    "console_clean"
  ],
  "max_retries": 4,
  "timeout_ms": 23631
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
