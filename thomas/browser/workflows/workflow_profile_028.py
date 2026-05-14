"""Workflow profile module: wf_profile_028."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_028",
  "category": "compliance",
  "title": "Compliance workflow profile 028",
  "risk_tier": "low",
  "required_signals": [
    "dom_ready",
    "network_idle",
    "console_clean"
  ],
  "max_retries": 1,
  "timeout_ms": 18836
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
