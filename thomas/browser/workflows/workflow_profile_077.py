"""Workflow profile module: wf_profile_077."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: dict[str, Any] = {
  "profile_id": "wf_profile_077",
  "category": "admin",
  "title": "Admin workflow profile 077",
  "risk_tier": "medium",
  "required_signals": [
    "dom_ready",
    "network_idle",
    "console_clean"
  ],
  "max_retries": 2,
  "timeout_ms": 25549
}

def get_profile() -> dict[str, Any]:
    return dict(PROFILE)
