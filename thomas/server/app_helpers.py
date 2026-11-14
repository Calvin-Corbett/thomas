"""Helper functions for app initialization."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from thomas.agent.runtime_skill_tools import register_runtime_skill_tools
from thomas.core.config import AppConfig, load_config
from thomas.core.kernel import late, seams
from thomas.server.app_keys import APP_CONFIG
from thomas.server.tool_extensions import register_all_optional_tools
from thomas.server.tool_groups import register_tool_group
from thomas.tools.code_search import register_code_search_tools
from thomas.tools.diff import register_diff_tools
from thomas.tools.filesystem import register_filesystem_tools
from thomas.tools.git import register_git_tools
from thomas.tools.goals import register_goal_tools
from thomas.tools.image_generation import register_image_generation_tools
from thomas.tools.registry import ToolRegistry
from thomas.tools.resilient_web_search import get_resilient_web_search_tool
from thomas.tools.shell import register_shell_tools
from thomas.tools.ssh import register_ssh_tools
from thomas.tools.web_search import get_web_fetch_tool

if TYPE_CHECKING:
    from aiohttp import web

import logging

log = logging.getLogger(__name__)


def _read_self_projects():
    # Import at call time: routes.self_project_routes also loads Build's start path.
    from thomas.server.routes.self_project_routes import read_projects

    return read_projects()


def _read_unlanded():
    # Import at call time: the ratchet's package belongs to its row, and Chat reads these records with that row off.
    from thomas.server.ratchet.report import read_report

    return read_report()


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
    # Declared in tool_manifests/code-search.toml; the direct call is the fallback.
    register_tool_group(
        registry,
        "code-search",
        {"sandbox": sandbox},
        fallback=lambda: register_code_search_tools(registry, sandbox),
    )
    from thomas.tools.repo_code_index import RepoIndexTool

    registry.register(RepoIndexTool(sandbox))
    register_diff_tools(registry, sandbox)
    register_goal_tools(registry, Path(sandbox))  # standing goals the contract holds every turn to

    # Thomas has been recording his own failures for months with no way to read
    # them back. Without this he cannot be asked what is broken, let alone fix it.
    from thomas.server import issue_ledger
    from thomas.tools.self_issues import register_self_issue_tools

    register_self_issue_tools(registry, issue_ledger.recent_issues)

    # What is still unlanded, from the ratchet's records (thomas/server/ratchet): Chat reads them, never git.
    from thomas.tools.self_unlanded import register_self_unlanded_tools

    register_self_unlanded_tools(registry, _read_unlanded)
    from thomas.tools.self_projects import register_self_projects_tools

    register_self_projects_tools(registry, _read_self_projects)
    register_ssh_tools(registry)

    # Investigation tools -- registered only if investigation DB has cases
    try:
        from thomas.tools.investigation import register_investigation_tools

        register_investigation_tools(registry)
    except (ImportError, ModuleNotFoundError, OSError):
        pass

    # Web research is a core chat capability, not an optional domain module.
    # The implementations already fail with actionable ToolResults when an
    # upstream provider is unavailable, so always expose both tools to chat and
    # worker runtimes instead of leaving the existing implementation orphaned.
    registry.register(get_resilient_web_search_tool())
    registry.register(get_web_fetch_tool())

    # Image generation is a first-class capability, like web research: always
    # registered, honest call-time error when no image-capable key exists.
    # The secret reader surfaces keys saved via Settings > Models (SecretStore);
    # built lazily so a missing/broken store never blocks tool registration.
    def _image_secret_reader(profile: str) -> str | None:
        from thomas.server.app_core import _secret_store_root
        from thomas.server.secrets import SecretStore

        return SecretStore(_secret_store_root(config)).get(profile)

    register_image_generation_tools(
        registry,
        config,
        Path(sandbox),
        secret_reader=_image_secret_reader,
    )
    register_runtime_skill_tools(registry, config, Path(sandbox))

    # Register all optional domain module tools
    register_all_optional_tools(registry)

    # What rows lend to runs built from now on. A built-in keeps its name; a row's tool of that name is left out.
    from thomas.agent.kernel_wiring import contributed_tools

    for lent in contributed_tools():
        if registry.get(lent.name) is not None:
            log.warning("A row lends %s, a name the tools already hold; the row's is left out", lent.name)
            continue
        registry.register(lent)

    return registry


def add_tools_rows_lent_the_server(registry: ToolRegistry, shared: Any, sandbox: Any) -> None:
    """Give a run's tools what rows lent the server's own set, which is where a running server's rows put them.

    A row on a running server lends through its own kernel, and ``_build_tools`` reads the process one, so a run built
    there never sees it. A tool that works in the run's folder, such as ``browser.open``, is rebound to that folder. The
    loan stays the row's, so the copy refuses once the row stops.
    """
    from thomas.agent.kernel_wiring import LentTool

    for lent in shared.list_tools() if shared is not None else []:
        if isinstance(lent, LentTool) and registry.get(lent.name) is None:
            rebind = getattr(lent.inner, "for_workspace", None)
            registry.register(LentTool(rebind(sandbox), lent.lending) if callable(rebind) else lent)


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


late.provide(seams.TOOL_SET, lambda config: _build_tools(config))
