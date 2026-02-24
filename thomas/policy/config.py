from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import tomllib  # py3.11+
except Exception:  # pragma: no cover
    tomllib = None  # type: ignore

def _env_bool(name: str, default: Optional[bool] = None) -> Optional[bool]:
    v = os.environ.get(name)
    if v is None:
        return default
    v = v.strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    return default

@dataclass
class GuardrailsSettings:
    enabled: bool = False
    approval_timeout_s: int = 60
    # If true, only certain tools require approvals; otherwise use rules.
    tools_require_approval: List[str] = field(default_factory=list)

@dataclass
class PolicyConfig:
    guardrails: GuardrailsSettings = field(default_factory=GuardrailsSettings)

    # Rule tuning:
    deny_roots: List[str] = field(default_factory=list)
    deny_paths: List[str] = field(default_factory=list)
    approval_roots: List[str] = field(default_factory=list)
    allow_tools: List[str] = field(default_factory=list)
    deny_tools: List[str] = field(default_factory=list)
    deny_groups: List[str] = field(default_factory=list)  # e.g. ["shell", "browser", "git"]

    # Redaction tuning:
    redact_additional_patterns: List[str] = field(default_factory=list)

    @staticmethod
    def from_mapping(m: Dict[str, Any]) -> "PolicyConfig":
        g = m.get("guardrails") or {}
        cfg = PolicyConfig()
        cfg.guardrails.enabled = bool(g.get("enabled", cfg.guardrails.enabled))
        cfg.guardrails.approval_timeout_s = int(g.get("approval_timeout_s", cfg.guardrails.approval_timeout_s))
        cfg.guardrails.tools_require_approval = list(g.get("tools_require_approval", cfg.guardrails.tools_require_approval))
        cfg.deny_roots = list(m.get("deny_roots", cfg.deny_roots))
        cfg.deny_paths = list(m.get("deny_paths", cfg.deny_paths))
        cfg.approval_roots = list(m.get("approval_roots", cfg.approval_roots))
        cfg.allow_tools = list(m.get("allow_tools", cfg.allow_tools))
        cfg.deny_tools = list(m.get("deny_tools", cfg.deny_tools))
        cfg.deny_groups = list(m.get("deny_groups", cfg.deny_groups))
        cfg.redact_additional_patterns = list(m.get("redact_additional_patterns", cfg.redact_additional_patterns))
        return cfg

def _load_toml(path: Path) -> Dict[str, Any]:
    if tomllib is None:
        raise RuntimeError("tomllib not available (need Python 3.11+)")
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}

def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))

def load_policy_config(runtime_root: str) -> PolicyConfig:
    """Load config from runtime/.thomas/policy.toml preferred, fallback to policy.json.

    Also respects env var:
      - THOMAS_GUARDRAILS=1/0 to force enable/disable.
    """
    rr = Path(runtime_root)
    cfg_dir = rr / ".thomas"
    toml_path = cfg_dir / "policy.toml"
    json_path = cfg_dir / "policy.json"

    mapping: Dict[str, Any] = {}
    if toml_path.exists():
        mapping = _load_toml(toml_path)
    elif json_path.exists():
        mapping = _load_json(json_path)

    cfg = PolicyConfig.from_mapping(mapping)

    env_override = _env_bool("THOMAS_GUARDRAILS", None)
    if env_override is not None:
        cfg.guardrails.enabled = env_override

    to = os.environ.get("THOMAS_GUARDRAILS_TIMEOUT_S")
    if to:
        try:
            cfg.guardrails.approval_timeout_s = max(1, int(to))
        except ValueError:
            pass
    return cfg
