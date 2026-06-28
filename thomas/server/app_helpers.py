"""Helper functions for app initialization."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from thomas.core.config import AppConfig, load_config
from thomas.server.app_keys import APP_CONFIG
from thomas.server.tool_extensions import register_all_optional_tools
from thomas.tools.code_search import register_code_search_tools
from thomas.tools.diff import register_diff_tools
from thomas.tools.filesystem import register_filesystem_tools
from thomas.tools.git import register_git_tools
from thomas.tools.registry import ToolRegistry
from thomas.tools.shell import register_shell_tools
from thomas.tools.ssh import register_ssh_tools

if TYPE_CHECKING:
    from aiohttp import web

import logging

log = logging.getLogger(__name__)

try:
    from thomas.memory.autonomy import AutonomyMemoryEngine
except (ImportError, ModuleNotFoundError):  # pragma: no cover
    AutonomyMemoryEngine = None  # type: ignore[assignment]


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


class _FallbackSecretStore:
    """Graceful fallback when SecretStore initialization is unavailable."""

    def get(self, _key: str, default: str | None = None) -> str | None:
        return default


def _appkey_identity(key: Any) -> str:
    rep = repr(key)
    match = re.match(r"^<AppKey\(([^,]+),\s*type=.*\)>$", rep)
    if match:
        name = str(match.group(1) or "")
        marker = "thomas.server.app_keys."
        idx = name.find(marker)
        if idx >= 0:
            return name[idx:]
        return name
    return str(key)


def _resolve_app_value(
    app: web.Application,
    key: Any,
    *,
    expected_type: Any = None,
    default: Any = None,
    required: bool = False,
) -> Any:
    value = app.get(key)
    if expected_type is None:
        if value is not None:
            return value
    elif isinstance(value, expected_type):
        return value

    target_identity = _appkey_identity(key)
    for existing_key, existing_value in app.items():
        if _appkey_identity(existing_key) != target_identity:
            continue
        if expected_type is not None and not isinstance(existing_value, expected_type):
            continue
        app[key] = existing_value
        return existing_value

    if required:
        raise KeyError(key)
    return default


def _resolve_runtime_config(app: web.Application) -> AppConfig:
    cfg = _resolve_app_value(app, APP_CONFIG, expected_type=AppConfig)
    if isinstance(cfg, AppConfig):
        return cfg
    for value in app.values():
        if isinstance(value, AppConfig):
            app[APP_CONFIG] = value
            return value
    cfg = load_config()
    app[APP_CONFIG] = cfg
    return cfg


def _web_dir() -> Path:
    return Path(__file__).resolve().parent / "web"


def _build_tools(config: AppConfig) -> ToolRegistry:
    registry = ToolRegistry()
    sandbox = config.tools.sandbox_path
    register_filesystem_tools(
        registry,
        sandbox,
        config.tools.max_file_size,
        file_access=getattr(config.tools, "file_access", 1),
    )
    if config.tools.allow_shell:
        register_shell_tools(
            registry,
            sandbox,
            config_timeout=config.tools.shell_timeout,
            allowed=True,
        )
    register_git_tools(registry, sandbox)
    register_code_search_tools(registry, sandbox)
    register_diff_tools(registry, sandbox)
    register_ssh_tools(registry)

    # Investigation tools -- registered only if investigation DB has cases
    try:
        from thomas.tools.investigation import register_investigation_tools

        register_investigation_tools(registry)
    except (ImportError, ModuleNotFoundError, OSError):
        pass

    # Browser automation tools (Playwright) -- registered only if the
    # ``playwright`` package is installed; otherwise the tools would only fail
    # at call time. register_browser_tools() performs the find_spec gate.
    try:
        from thomas.tools.browser import register_browser_tools

        register_browser_tools(registry)
    except (ImportError, ModuleNotFoundError):
        pass

    # Register all optional domain module tools
    register_all_optional_tools(registry)

    return registry


def _build_memory(config: AppConfig):
    # Resolve via sys.modules so tests that
    # `monkeypatch.setattr(thomas.server.app, "AutonomyMemoryEngine", ...)`
    # actually intercept this lookup. The bare module-level alias above is
    # only the fallback when the patched attribute is absent. See
    # ``tests/test_memory_runtime_bootstrap.py``.
    import sys

    engine_cls = None
    for module_name in ("thomas.server.app", "thomas.server.app_helpers"):
        module = sys.modules.get(module_name)
        if module is not None:
            candidate = getattr(module, "AutonomyMemoryEngine", None)
            if candidate is not None:
                engine_cls = candidate
                break
    if engine_cls is None:
        engine_cls = AutonomyMemoryEngine
    if engine_cls is None:
        return None
    try:
        engine = engine_cls(
            config,
            enable_v2=_env_flag("THOMAS_MEMORY_V2_ENABLED", True),
            enable_legacy=_env_flag("THOMAS_MEMORY_LEGACY_ENABLED", False),
        )
        engine.start()
        return engine
    except (OSError, RuntimeError, TypeError, ValueError) as e:
        log.warning("Memory engine failed to start: %s", e)
        return None
