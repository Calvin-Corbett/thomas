"""Workflow profile module: wf_profile_126."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: Dict[str, Any] = {
  "profile_id": "wf_profile_126",
  "category": "retention",
  "title": "Retention workflow profile 126",
  "risk_tier": "high",
  "required_signals": [
    "dom_ready",
    "network_idle",
    "console_clean"
  ],
  "max_retries": 3,
  "timeout_ms": 32262
}

def get_profile() -> Dict[str, Any]:
    return dict(PROFILE)
