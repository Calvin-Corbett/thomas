"""Workflow profile module: wf_profile_168."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_168",
  "category": "content",
  "title": "Content workflow profile 168",
  "risk_tier": "high",
  "required_signals": [
    "dom_ready",
    "network_idle",
    "console_clean"
  ],
  "max_retries": 1,
  "timeout_ms": 38016
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
