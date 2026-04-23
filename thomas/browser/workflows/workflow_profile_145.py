"""Workflow profile module: wf_profile_145."""

from __future__ import annotations

from typing import Any, Dict

PROFILE: Dict[str, Any] = {
  "profile_id": "wf_profile_145",
  "category": "checkout",
  "title": "Checkout workflow profile 145",
  "risk_tier": "low",
  "required_signals": [
    "metrics_snapshot",
    "event_log_complete",
    "dom_ready"
  ],
  "max_retries": 2,
  "timeout_ms": 34865
}

def get_profile() -> Dict[str, Any]:
    return dict(PROFILE)
