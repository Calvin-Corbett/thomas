from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict

try:
    import tomllib as _toml_loader  # py3.11+
except Exception:  # pragma: no cover
    try:
        import tomli as _toml_loader  # type: ignore
    except Exception:  # pragma: no cover
        _toml_loader = None  # type: ignore

DEFAULT_POLICY = {
    "risk": {
        "low": {"mode": "allow"},
        "medium": {"mode": "approve"},
        "high": {"mode": "deny"},
        "critical": {"mode": "deny"},
    },
    "kinds": {
        # Fine-grained overrides by job kind.
        # Example:
        # "reminder": {"risk_class": "low", "mode": "allow"},
    },
    "api": {
        "require_token": False,
    },
}


@dataclass
class PolicyDecision:
    allowed: bool
    requires_approval: bool
    reason: str


@dataclass
class AutonomyPolicy:
    policy: Dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_POLICY))

    @staticmethod
    def load(policy_path: str) -> "AutonomyPolicy":
        if not policy_path or not os.path.exists(policy_path):
            return AutonomyPolicy()
        if _toml_loader is None:
            raise RuntimeError("TOML loader unavailable; install tomli for Python < 3.11")
        with open(policy_path, "rb") as f:
            data = _toml_loader.load(f) or {}
        merged = dict(DEFAULT_POLICY)
        # shallow merge for top-level keys
        for k, v in data.items():
            if isinstance(v, dict) and isinstance(merged.get(k), dict):
                merged[k] = {**merged[k], **v}
            else:
                merged[k] = v
        # nested merges for known dicts
        if "risk" in data and isinstance(data["risk"], dict):
            merged["risk"] = {**DEFAULT_POLICY["risk"], **data["risk"]}
        if "kinds" in data and isinstance(data["kinds"], dict):
            merged["kinds"] = {**DEFAULT_POLICY["kinds"], **data["kinds"]}
        if "api" in data and isinstance(data["api"], dict):
            merged["api"] = {**DEFAULT_POLICY["api"], **data["api"]}
        return AutonomyPolicy(policy=merged)

    def to_json(self) -> dict:
        """Return a JSON-serializable view of the effective policy.

        Keep this intentionally boring and stable: the UI and API consumers should
        not depend on Python-side computed properties that may drift.
        """
        return {
            "risk": dict(self.policy.get("risk") or {}),
            "kinds": dict(self.policy.get("kinds") or {}),
            "api": dict(self.policy.get("api") or {}),
        }

    def decision_for_job(self, kind: str, risk_class: str) -> PolicyDecision:
        kind_over = (self.policy.get("kinds") or {}).get(kind) or {}
        # kind override can change risk or mode
        rc = kind_over.get("risk_class", risk_class)
        risk_cfg = (self.policy.get("risk") or {}).get(rc) or {}
        mode = kind_over.get("mode", risk_cfg.get("mode", "deny"))

        if mode == "allow":
            return PolicyDecision(True, False, f"{rc}: allowed by policy")
        if mode == "approve":
            return PolicyDecision(True, True, f"{rc}: requires approval by policy")
        return PolicyDecision(False, False, f"{rc}: denied by policy")

    def api_require_token(self) -> bool:
        return bool((self.policy.get("api") or {}).get("require_token", False))




