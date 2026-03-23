from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from typing import Any

try:
    import tomllib as _toml_loader  # py3.11+
except ImportError:  # pragma: no cover
    try:
        import tomli as _toml_loader  # type: ignore
    except ImportError:  # pragma: no cover
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
        "no_human_mode": "human",
    },
}

_NO_HUMAN_MODES = {"human", "allow", "deny"}


@dataclass
class PolicyDecision:
    allowed: bool
    requires_approval: bool
    reason: str


@dataclass
class AutonomyPolicy:
    policy: dict[str, Any] = field(default_factory=lambda: copy.deepcopy(DEFAULT_POLICY))

    @staticmethod
    def _normalize_no_human_mode(value: Any) -> str:
        mode = str(value or "human").strip().lower()
        if mode not in _NO_HUMAN_MODES:
            return "human"
        return mode

    @staticmethod
    def load(policy_path: str) -> AutonomyPolicy:
        if not policy_path or not os.path.exists(policy_path):
            return AutonomyPolicy()
        if _toml_loader is None:
            raise RuntimeError("TOML loader unavailable; install tomli for Python < 3.11")
        with open(policy_path, "rb") as f:
            data = _toml_loader.load(f) or {}
        merged = copy.deepcopy(DEFAULT_POLICY)
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
        env_mode = (
            os.environ.get("THOMAS_AUTONOMY_NO_HUMAN_MODE")
            or os.environ.get("THOMAS_NO_HUMAN_MODE")
            or os.environ.get("THOMAS_GUARDRAILS_NO_HUMAN_MODE")
        )
        if env_mode:
            merged["api"]["no_human_mode"] = AutonomyPolicy._normalize_no_human_mode(env_mode)
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

    @property
    def no_human_mode(self) -> str:
        return self._normalize_no_human_mode((self.policy.get("api") or {}).get("no_human_mode"))

    def decision_for_job(self, kind: str, risk_class: str) -> PolicyDecision:
        kind_over = (self.policy.get("kinds") or {}).get(kind) or {}
        # kind override can change risk or mode
        rc = kind_over.get("risk_class", risk_class)
        risk_cfg = (self.policy.get("risk") or {}).get(rc) or {}
        mode = kind_over.get("mode", risk_cfg.get("mode", "deny"))

        if mode == "allow":
            return PolicyDecision(True, False, f"{rc}: allowed by policy")
        if mode == "approve":
            no_human_mode = self.no_human_mode
            if no_human_mode == "allow":
                return PolicyDecision(
                    True,
                    False,
                    f"{rc}: auto-approved by no-human mode.",
                )
            if no_human_mode == "deny":
                return PolicyDecision(
                    False,
                    False,
                    f"{rc}: blocked by no-human mode; approval required by policy and not allowed.",
                )
            return PolicyDecision(True, True, f"{rc}: requires approval by policy")
        return PolicyDecision(False, False, f"{rc}: denied by policy")

    def api_require_token(self) -> bool:
        return bool((self.policy.get("api") or {}).get("require_token", False))
