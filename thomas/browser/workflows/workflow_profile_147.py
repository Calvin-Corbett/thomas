"""Workflow profile module: wf_profile_147."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: Dict[str, Any] = {
  "profile_id": "wf_profile_147",
  "category": "support",
  "title": "Support workflow profile 147",
  "risk_tier": "high",
  "required_signals": [
    "dom_ready",
    "network_idle",
    "console_clean"
  ],
  "max_retries": 4,
  "timeout_ms": 35139
}

def get_profile() -> Dict[str, Any]:
    return dict(PROFILE)
