"""Workflow profile module: wf_profile_169."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_169",
  "category": "search",
  "title": "Search workflow profile 169",
  "risk_tier": "low",
  "required_signals": [
    "network_idle",
    "console_clean",
    "trace_available"
  ],
  "max_retries": 2,
  "timeout_ms": 38153
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
