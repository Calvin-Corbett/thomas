"""Workflow profile module: wf_profile_086."""

from __future__ import annotations

from typing import Any

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_086",
  "category": "audit",
  "title": "Audit workflow profile 086",
  "risk_tier": "medium",
  "required_signals": [
    "console_clean",
    "trace_available",
    "screenshot_saved"
  ],
  "max_retries": 3,
  "timeout_ms": 26782
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
