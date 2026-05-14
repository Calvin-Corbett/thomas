"""Workflow profile module: wf_profile_093."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_093",
  "category": "support",
  "title": "Support workflow profile 093",
  "risk_tier": "high",
  "required_signals": [
    "console_clean",
    "trace_available",
    "screenshot_saved"
  ],
  "max_retries": 2,
  "timeout_ms": 27741
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
