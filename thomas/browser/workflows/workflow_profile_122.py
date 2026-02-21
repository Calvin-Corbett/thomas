"""Workflow profile module: wf_profile_122."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: Dict[str, Any] = {
  "profile_id": "wf_profile_122",
  "category": "audit",
  "title": "Audit workflow profile 122",
  "risk_tier": "medium",
  "required_signals": [
    "trace_available",
    "screenshot_saved",
    "metrics_snapshot"
  ],
  "max_retries": 3,
  "timeout_ms": 31714
}

def get_profile() -> Dict[str, Any]:
    return dict(PROFILE)
