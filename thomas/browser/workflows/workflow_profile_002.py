"""Workflow profile module: wf_profile_002."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_002",
  "category": "auth",
  "title": "Auth workflow profile 002",
  "risk_tier": "medium",
  "required_signals": [
    "console_clean",
    "trace_available",
    "screenshot_saved"
  ],
  "max_retries": 3,
  "timeout_ms": 15274
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
