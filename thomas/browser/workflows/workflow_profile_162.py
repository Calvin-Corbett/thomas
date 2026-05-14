"""Workflow profile module: wf_profile_162."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_162",
  "category": "retention",
  "title": "Retention workflow profile 162",
  "risk_tier": "high",
  "required_signals": [
    "network_idle",
    "console_clean",
    "trace_available"
  ],
  "max_retries": 3,
  "timeout_ms": 37194
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
