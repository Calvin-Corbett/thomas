"""Workflow profile module: wf_profile_155."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_155",
  "category": "payments",
  "title": "Payments workflow profile 155",
  "risk_tier": "medium",
  "required_signals": [
    "network_idle",
    "console_clean",
    "trace_available"
  ],
  "max_retries": 4,
  "timeout_ms": 36235
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
