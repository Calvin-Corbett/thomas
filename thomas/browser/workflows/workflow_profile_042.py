"""Workflow profile module: wf_profile_042."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_042",
  "category": "content",
  "title": "Content workflow profile 042",
  "risk_tier": "high",
  "required_signals": [
    "dom_ready",
    "network_idle",
    "console_clean"
  ],
  "max_retries": 3,
  "timeout_ms": 20754
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
