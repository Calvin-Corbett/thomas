"""Workflow profile module: wf_profile_043."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_043",
  "category": "search",
  "title": "Search workflow profile 043",
  "risk_tier": "low",
  "required_signals": [
    "network_idle",
    "console_clean",
    "trace_available"
  ],
  "max_retries": 4,
  "timeout_ms": 20891
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
