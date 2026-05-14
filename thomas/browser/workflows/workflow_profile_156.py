"""Workflow profile module: wf_profile_156."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_156",
  "category": "risk",
  "title": "Risk workflow profile 156",
  "risk_tier": "high",
  "required_signals": [
    "console_clean",
    "trace_available",
    "screenshot_saved"
  ],
  "max_retries": 1,
  "timeout_ms": 36372
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
