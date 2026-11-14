from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib  # py3.11+
except Exception:  # pragma: no cover
    tomllib = None  # type: ignore


_NO_HUMAN_MODES = {"human", "allow", "deny"}


def _string_list(
    value: Any,
    *,
    field_name: str,
    validation_errors: list[str],
) -> list[str]:
    """Normalize one string or record an invalid list without raising."""
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        validation_errors.append(f"{field_name} must be a string or list of strings")
        return []
    if any(not isinstance(item, str) for item in value):
        validation_errors.append(f"{field_name} entries must all be strings")
        return []
    return list(value)


def _normalize_no_human_mode(value: str | None) -> str:
    mode = str(value or "human").strip().lower()
    if mode not in _NO_HUMAN_MODES:
        return "human"
    return mode


def _validated_no_human_mode(value: Any, *, validation_errors: list[str]) -> str:
    """Accept a mode the operator named; reject one nobody can interpret.

    Case and surrounding space are spelling, not meaning: "Deny" names an
    existing mode. Recording it as invalid would put DenyInvalidConfigRule
    first in the chain, which revokes every tool rather than entering the
    stricter mode that was asked for.
    """
    if isinstance(value, str):
        mode = value.strip().lower()
        if mode in _NO_HUMAN_MODES:
            return mode
    validation_errors.append("guardrails.no_human_mode must be one of: human, allow, deny")
    return "human"


def _validated_enabled(value: Any, *, default: bool, validation_errors: list[str]) -> bool:
    """Read an on/off switch the way the file meant it.

    ``enabled = 0`` is valid TOML for "turn guardrails off", and JSON writers
    emit 0/1 for booleans routinely. Recording that as a config error was the
    worst possible reading: the error routes to DenyInvalidConfigRule, which
    denies EVERY tool, while ``enabled`` stayed True — so asking to turn
    guardrails off turned everything off except guardrails.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        token = value.strip().lower()
        if token in ("true", "yes", "on", "1"):
            return True
        if token in ("false", "no", "off", "0"):
            return False
    validation_errors.append("guardrails.enabled must be true or false")
    return default


def _whole_seconds(value: Any) -> int | None:
    """Return ``value`` as whole seconds, or None when it is not a whole number.

    TOML, JSON and a hand-edited file spell the same duration as 60, 60.0 and
    "60". A fraction has no obvious rounding the operator would agree with, so
    it stays invalid. bool is excluded before the int branch: True is an int in
    Python, but nobody configures a one-second approval window that way.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return None
        return int(number) if number.is_integer() else None
    return None


def _validated_approval_timeout_s(value: Any, *, default: int, validation_errors: list[str]) -> int:
    """Zero is a choice ("do not wait"), not a failure to parse.

    Rejecting it denied every tool, which is a strange punishment for a number
    the previous parser accepted. Negative is still refused: there is no reading
    of "wait minus seven seconds".
    """
    seconds = _whole_seconds(value)
    if seconds is None or seconds < 0:
        validation_errors.append("guardrails.approval_timeout_s must be a whole number of seconds, zero or more")
        return default
    return seconds


def _env_bool(name: str, default: bool | None = None) -> bool | None:
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
    # Default ON per product decision D6 (PRODUCT_READY_PUSH_2026-07-15,
    # executed with Calvin's 2026-07-18 go-ahead): with guardrails reporting
    # unavailable, /api/health showed "degraded" on every boot and Work-mode
    # autonomy handoffs dead-ended. Opt out via THOMAS_GUARDRAILS=0 or
    # policy.toml [guardrails] enabled=false.
    enabled: bool = True
    approval_timeout_s: int = 60
    no_human_mode: str = "human"
    # If true, only certain tools require approvals; otherwise use rules.
    tools_require_approval: list[str] = field(default_factory=list)


@dataclass
class PolicyConfig:
    guardrails: GuardrailsSettings = field(default_factory=GuardrailsSettings)

    # Rule tuning:
    deny_roots: list[str] = field(default_factory=list)
    deny_paths: list[str] = field(default_factory=list)
    approval_roots: list[str] = field(default_factory=list)
    allow_tools: list[str] = field(default_factory=list)
    deny_tools: list[str] = field(default_factory=list)
    deny_groups: list[str] = field(default_factory=list)  # e.g. ["shell", "browser", "git"]

    # Redaction tuning:
    redact_additional_patterns: list[str] = field(default_factory=list)

    # Invalid policy input must reach PolicyEngine so it can deny every tool.
    validation_errors: list[str] = field(default_factory=list)

    @staticmethod
    def from_mapping(m: Any) -> PolicyConfig:
        cfg = PolicyConfig()
        if not isinstance(m, dict):
            cfg.validation_errors.append("policy root must be a table or object")
            return cfg

        g = m.get("guardrails", {})
        if g is None:
            # An explicit null is "I wrote the key and left it empty", which is
            # how the section reads when it is absent. Denying every tool over
            # it is not a reading anyone intended.
            g = {}
        elif not isinstance(g, dict):
            cfg.validation_errors.append("guardrails must be a table or object")
            g = {}

        cfg.guardrails.enabled = _validated_enabled(
            g.get("enabled", cfg.guardrails.enabled),
            default=cfg.guardrails.enabled,
            validation_errors=cfg.validation_errors,
        )

        cfg.guardrails.no_human_mode = _validated_no_human_mode(
            g.get("no_human_mode", cfg.guardrails.no_human_mode),
            validation_errors=cfg.validation_errors,
        )
        cfg.guardrails.approval_timeout_s = _validated_approval_timeout_s(
            g.get("approval_timeout_s", cfg.guardrails.approval_timeout_s),
            default=cfg.guardrails.approval_timeout_s,
            validation_errors=cfg.validation_errors,
        )
        cfg.guardrails.tools_require_approval = _string_list(
            g.get("tools_require_approval", cfg.guardrails.tools_require_approval),
            field_name="guardrails.tools_require_approval",
            validation_errors=cfg.validation_errors,
        )
        cfg.deny_roots = _string_list(
            m.get("deny_roots", cfg.deny_roots),
            field_name="deny_roots",
            validation_errors=cfg.validation_errors,
        )
        cfg.deny_paths = _string_list(
            m.get("deny_paths", cfg.deny_paths),
            field_name="deny_paths",
            validation_errors=cfg.validation_errors,
        )
        cfg.approval_roots = _string_list(
            m.get("approval_roots", cfg.approval_roots),
            field_name="approval_roots",
            validation_errors=cfg.validation_errors,
        )
        cfg.allow_tools = _string_list(
            m.get("allow_tools", cfg.allow_tools),
            field_name="allow_tools",
            validation_errors=cfg.validation_errors,
        )
        cfg.deny_tools = _string_list(
            m.get("deny_tools", cfg.deny_tools),
            field_name="deny_tools",
            validation_errors=cfg.validation_errors,
        )
        cfg.deny_groups = _string_list(
            m.get("deny_groups", cfg.deny_groups),
            field_name="deny_groups",
            validation_errors=cfg.validation_errors,
        )
        cfg.redact_additional_patterns = _string_list(
            m.get("redact_additional_patterns", cfg.redact_additional_patterns),
            field_name="redact_additional_patterns",
            validation_errors=cfg.validation_errors,
        )
        return cfg


def _load_toml(path: Path) -> dict[str, Any]:
    if tomllib is None:
        raise RuntimeError("tomllib not available (need Python 3.11+)")
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _load_json(path: Path) -> Any:
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

    mapping: Any = {}
    try:
        if toml_path.exists():
            mapping = _load_toml(toml_path)
        elif json_path.exists():
            mapping = _load_json(json_path)
        cfg = PolicyConfig.from_mapping(mapping)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        cfg = PolicyConfig(validation_errors=[f"policy file could not be loaded ({type(exc).__name__})"])

    env_override = _env_bool("THOMAS_GUARDRAILS", None)
    if env_override is not None:
        cfg.guardrails.enabled = env_override

    cfg.guardrails.no_human_mode = _normalize_no_human_mode(
        os.environ.get("THOMAS_NO_HUMAN_MODE")
        or os.environ.get("THOMAS_GUARDRAILS_NO_HUMAN_MODE")
        or cfg.guardrails.no_human_mode
    )

    to = os.environ.get("THOMAS_GUARDRAILS_TIMEOUT_S")
    if to:
        try:
            cfg.guardrails.approval_timeout_s = max(1, int(to))
        except ValueError:
            pass
    return cfg
