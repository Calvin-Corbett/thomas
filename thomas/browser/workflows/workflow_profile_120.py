"""Workflow profile module: wf_profile_120."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_120",
  "category": "risk",
  "title": "Risk workflow profile 120",
  "risk_tier": "high",
  "required_signals": [
    "network_idle",
    "console_clean",
    "trace_available"
  ],
  "max_retries": 1,
  "timeout_ms": 31440
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
