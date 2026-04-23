"""Workflow profile module: wf_profile_176."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: Dict[str, Any] = {
  "profile_id": "wf_profile_176",
  "category": "audit",
  "title": "Audit workflow profile 176",
  "risk_tier": "medium",
  "required_signals": [
    "network_idle",
    "console_clean",
    "trace_available"
  ],
  "max_retries": 1,
  "timeout_ms": 39112
}

def get_profile() -> Dict[str, Any]:
    return dict(PROFILE)
