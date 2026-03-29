#!/usr/bin/env python3
"""Config loader for the Agent Safety framework.

Every hook imports this module to get its settings. The config is read
from `agent_safety.toml` in the repo root. If the file doesn't exist,
sensible defaults are used so hooks still work out of the box.

Usage in a hook:
    from agent_safety_config import config

    # Access any section
    protected_files = config.protected_policy_files()
    soft_limit = config.python_soft_limit()
    forbidden_pairs = config.circular_import_pairs()

The config is loaded once and cached for the lifetime of the process.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

# Locate repo root (parent of scripts/)
ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "agent_safety.toml"
CONFIG_ENV = "THOMAS_AGENT_SAFETY_CONFIG"


def _load_toml(path: Path) -> dict[str, Any]:
    """Load a TOML file. Uses tomllib (3.11+) or falls back to tomli."""
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    try:
        import tomllib

        return tomllib.loads(text)
    except ImportError:
        pass
    try:
        import tomli

        return tomli.loads(text)
    except ImportError as exc:
        raise RuntimeError(
            "agent_safety.toml requires Python 3.11+ (tomllib) or the tomli package to be installed"
        ) from exc


class AgentSafetyConfig:
    """Typed access to agent_safety.toml settings."""

    def __init__(self, data: dict[str, Any] | None = None):
        self._data = data or {}

    def _get(self, *keys: str, default: Any = None) -> Any:
        """Nested key lookup with default."""
        current = self._data
        for key in keys:
            if isinstance(current, dict):
                current = current.get(key)
                if current is None:
                    return default
            else:
                return default
        return current

    # ── Project ──────────────────────────────────────────────────────────

    def project_name(self) -> str:
        return str(self._get("project", "name", default="unknown"))

    def source_dirs(self) -> list[str]:
        return list(self._get("project", "source_dirs", default=["src/"]))

    def test_dirs(self) -> list[str]:
        return list(self._get("project", "test_dirs", default=["tests/"]))

    def all_code_dirs(self) -> list[str]:
        return self.source_dirs() + self.test_dirs()

    def worktree_max_uncommitted_changed_lines(self) -> int:
        return int(self._get("worktree_hygiene", "max_uncommitted_changed_lines", default=300))

    def worktree_change_budget_ignore_prefixes(self) -> list[str]:
        return list(
            self._get(
                "worktree_hygiene",
                "change_budget_ignore_prefixes",
                default=["output/", "runtime/", "artifacts/", "tmp/", ".venv/", "node_modules/"],
            )
        )

    # ── File Size Limits ─────────────────────────────────────────────────

    def python_soft_limit(self) -> int:
        return int(self._get("limits", "python_soft", default=800))

    def python_hard_limit(self) -> int:
        return int(self._get("limits", "python_hard", default=1200))

    def js_hard_limit(self) -> int:
        return int(self._get("limits", "js_hard", default=2000))

    # ── Protected Files ──────────────────────────────────────────────────

    def protected_policy_files(self) -> list[str]:
        return list(self._get("protected", "policy_files", default=[]))

    def protected_guardrails_files(self) -> list[str]:
        return list(self._get("protected", "guardrails_files", default=[]))

    def protected_enforcement_files(self) -> list[str]:
        return list(self._get("protected", "enforcement_files", default=[]))

    def protected_enforcement_scripts(self) -> list[str]:
        return list(self._get("protected", "enforcement_scripts", default=[]))

    def all_protected_files(self) -> set[str]:
        return set(
            self.protected_policy_files()
            + self.protected_guardrails_files()
            + self.protected_enforcement_files()
            + self.protected_enforcement_scripts()
        )

    # ── Stubs ────────────────────────────────────────────────────────────

    def placeholder_files(self) -> list[str]:
        return list(self._get("stubs", "placeholder_files", default=[]))

    def build_output_files(self) -> list[str]:
        return list(self._get("stubs", "build_output_files", default=[]))

    # ── Exception Handling ───────────────────────────────────────────────

    def require_specific_exceptions(self) -> bool:
        return bool(self._get("exceptions", "require_specific", default=True))

    def broad_catch_requires(self) -> list[str]:
        return list(self._get("exceptions", "broad_catch_requires", default=["logging", "reraise"]))

    def exception_ratchet(self) -> bool:
        return bool(self._get("exceptions", "ratchet", default=True))

    # ── Duplicates ───────────────────────────────────────────────────────

    def forbidden_suffixes(self) -> list[str]:
        return list(
            self._get(
                "duplicates",
                "forbidden_suffixes",
                default=[
                    "_v2",
                    "_new",
                    "_fixed",
                    "_copy",
                    "_backup",
                    "_old",
                ],
            )
        )

    def forbidden_prefixes(self) -> list[str]:
        return list(
            self._get(
                "duplicates",
                "forbidden_prefixes",
                default=[
                    "new_",
                    "copy_of_",
                    "backup_",
                    "old_",
                ],
            )
        )

    # ── Changelog ────────────────────────────────────────────────────────

    def changelog_required(self) -> bool:
        return bool(self._get("changelog", "required", default=True))

    def changelog_file(self) -> str:
        return str(self._get("changelog", "file", default="CHANGELOG.md"))

    def changelog_threshold(self) -> int:
        return int(self._get("changelog", "threshold", default=3))

    # ── Circular Imports ─────────────────────────────────────────────────

    def module_prefix(self) -> str:
        return str(self._get("circular_imports", "module_prefix", default="src"))

    def circular_import_pairs(self) -> list[tuple[str, str]]:
        raw = self._get("circular_imports", "forbidden_pairs", default=[])
        return [(str(pair[0]), str(pair[1])) for pair in raw if len(pair) >= 2]

    # ── Boot Smoke ───────────────────────────────────────────────────────

    def boot_trigger_dirs(self) -> list[str]:
        return list(self._get("boot_smoke", "trigger_on_dirs", default=[]))

    def boot_imports(self) -> list[str]:
        return list(self._get("boot_smoke", "imports", default=[]))

    # ── Type Safety ──────────────────────────────────────────────────────

    def type_safety_enabled(self) -> bool:
        return bool(self._get("type_safety", "enabled", default=False))

    def type_safety_tool(self) -> str:
        return str(self._get("type_safety", "tool", default="mypy"))

    def type_safety_args(self) -> list[str]:
        return list(self._get("type_safety", "args", default=["--ignore-missing-imports"]))

    def type_safety_files(self) -> list[str]:
        return list(self._get("type_safety", "enabled_files", default=[]))

    # Skip policy

    def skip_policy_protected_hooks(self) -> list[str]:
        return list(self._get("skip_policy", "protected_hooks", default=[]))

    def skip_policy_max_skip_hooks(self) -> int:
        return int(self._get("skip_policy", "max_skip_hooks", default=4))

    def skip_policy_max_staged_files_with_skip(self) -> int:
        return int(self._get("skip_policy", "max_staged_files_with_skip", default=200))

    def skip_policy_max_staged_files_with_breakglass(self) -> int:
        return int(self._get("skip_policy", "max_staged_files_with_breakglass", default=60))

    def skip_policy_breakglass_max_per_agent_24h(self) -> int:
        return int(self._get("skip_policy", "breakglass_max_per_agent_24h", default=3))

    def skip_policy_breakglass_cooldown_minutes(self) -> int:
        return int(self._get("skip_policy", "breakglass_cooldown_minutes", default=15))

    # ── Dead Code ────────────────────────────────────────────────────────

    def dead_code_dirs(self) -> list[str]:
        return list(self._get("dead_code", "directories", default=[]))

    def dead_code_redirect(self) -> str:
        return str(self._get("dead_code", "redirect_to", default=""))


# ── Singleton ────────────────────────────────────────────────────────────────

_cached_config: AgentSafetyConfig | None = None
_cached_config_path: Path | None = None


def _resolve_config_path(path: Path | None = None) -> Path:
    explicit = path
    if explicit is not None:
        return explicit
    env_value = str(os.getenv(CONFIG_ENV, "")).strip()
    if env_value:
        return Path(env_value).expanduser().resolve()
    return CONFIG_PATH


def load_config(path: Path | None = None) -> AgentSafetyConfig:
    """Load and cache the config. Thread-safe for single-process hooks."""
    global _cached_config, _cached_config_path
    config_path = _resolve_config_path(path)
    if _cached_config is not None and _cached_config_path == config_path:
        return _cached_config
    data = _load_toml(config_path)
    cfg = AgentSafetyConfig(data)
    _cached_config = cfg
    _cached_config_path = config_path
    return cfg


def clear_config_cache() -> None:
    """Drop the cached config, typically for tests that swap config paths."""
    global _cached_config, _cached_config_path
    _cached_config = None
    _cached_config_path = None


# Convenience: import config directly
config = load_config()
