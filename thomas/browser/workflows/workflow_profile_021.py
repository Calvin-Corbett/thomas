"""Workflow profile module: wf_profile_021."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_021",
  "category": "support",
  "title": "Support workflow profile 021",
  "risk_tier": "high",
  "required_signals": [
    "dom_ready",
    "network_idle",
    "console_clean"
  ],
  "max_retries": 2,
  "timeout_ms": 17877
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
