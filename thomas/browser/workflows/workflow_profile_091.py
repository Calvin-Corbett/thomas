"""Workflow profile module: wf_profile_091."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_091",
  "category": "checkout",
  "title": "Checkout workflow profile 091",
  "risk_tier": "low",
  "required_signals": [
    "dom_ready",
    "network_idle",
    "console_clean"
  ],
  "max_retries": 4,
  "timeout_ms": 27467
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
