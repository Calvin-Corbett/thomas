"""Runtime loader for enabled plugin instances.

This module bridges the *installed plugins manifest* (written by
``p102_plugin_install_from_local_path``) and the *enable/disable state store*
(``p101_plugin_enable_and_disable_state_store``) to produce a list of live
plugin instances that the agent loop can dispatch hooks into via
``p108_plugin_hook_runner_core.run_hook``.

Contract:
    get_enabled_plugin_instances(install_root) -> list[Any]

Design rules (deliberate):
- NEVER raise. A broken/missing manifest, a plugin that fails to import, or a
  plugin with no recognizable entrypoint is skipped silently (logged at debug).
  Returning ``[]`` is always a valid answer.
- Results are cached per resolved install-root (keyed by absolute path + the
  manifest's mtime) so repeated turns don't re-import every plugin. Pass a new
  root or mutate the manifest to invalidate.
- A plugin instance is obtained from the FIRST recognizable entrypoint:
  ``get_plugin()`` -> ``create_plugin()`` -> module-level ``PLUGIN``. This
  matches the real entrypoints exposed by p109..p112.

Why file-based import (not dotted import): installed plugins live under
``<install_root>/<name>/`` which is generally NOT on ``sys.path``. We import
each plugin package from its ``__init__.py`` using ``importlib.util``; if the
package ``__init__`` exposes no entrypoint we scan its top-level ``.py`` modules
for one. This mirrors the discovery approach in p100.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import sys
import threading
from pathlib import Path
from typing import Any

from thomas.plugins.p101_plugin_enable_and_disable_state_store import (
    PluginEnablementStore,
    PluginEnablementStoreError,
    resolve_enablement_store_path,
)

log = logging.getLogger(__name__)

MANIFEST_FILENAME = "installed_plugins.json"

# Entrypoints we recognize on a plugin module, in priority order.
_ENTRYPOINT_FUNCS = ("get_plugin", "create_plugin")
_ENTRYPOINT_ATTRS = ("PLUGIN", "plugin")

# Cache: resolved-install-root -> (manifest_mtime, [instances])
_CACHE: dict[str, tuple[float, list[Any]]] = {}
_CACHE_LOCK = threading.Lock()


def get_enabled_plugin_instances(install_root: str | Path | None) -> list[Any]:
    """Return live instances for every *enabled* installed plugin.

    Args:
        install_root: Directory containing ``installed_plugins.json`` and the
            installed plugin packages. If ``None``/empty, returns ``[]`` (there
            is nothing to load).

    Returns:
        A list of plugin instances (possibly empty). Never raises.
    """
    if not install_root:
        return []

    try:
        root = Path(install_root).expanduser().resolve()
    except (OSError, ValueError, RuntimeError) as exc:  # REVIEWED: isolate path errors
        log.debug("Plugin runtime: invalid install_root %r: %s", install_root, exc)
        return []

    manifest_path = root / MANIFEST_FILENAME
    try:
        manifest_mtime = manifest_path.stat().st_mtime
    except OSError:
        # No manifest -> nothing installed. Cache the empty answer cheaply.
        manifest_mtime = -1.0

    cache_key = str(root)
    with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
        if cached is not None and cached[0] == manifest_mtime:
            return list(cached[1])

    instances = _load_enabled_instances(root, manifest_path)

    with _CACHE_LOCK:
        _CACHE[cache_key] = (manifest_mtime, list(instances))
    return list(instances)


def clear_cache() -> None:
    """Drop the cached plugin instances (test/util helper)."""
    with _CACHE_LOCK:
        _CACHE.clear()


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _load_enabled_instances(root: Path, manifest_path: Path) -> list[Any]:
    manifest = _read_manifest(manifest_path)
    if not manifest:
        return []

    plugins_map = manifest.get("plugins")
    if not isinstance(plugins_map, dict):
        return []

    store = _enablement_store(root)

    instances: list[Any] = []
    for name in sorted(plugins_map.keys()):
        entry = plugins_map.get(name)
        if not isinstance(entry, dict):
            continue

        if store is not None and not _is_enabled(store, name):
            continue

        installed_path = entry.get("installed_path") or str(root / name)
        instance = _instantiate_plugin(name, Path(installed_path))
        if instance is not None:
            instances.append(instance)

    return instances


def _read_manifest(manifest_path: Path) -> dict[str, Any] | None:
    if not manifest_path.is_file():
        return None
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError, UnicodeDecodeError) as exc:
        log.debug("Plugin runtime: failed to read manifest %s: %s", manifest_path, exc)
        return None
    if not isinstance(data, dict):
        return None
    return data


def _enablement_store(root: Path) -> PluginEnablementStore | None:
    """Resolve the enablement store, preferring one co-located with install_root.

    p101 resolves a default path from env/home; that's fine in production. To
    keep the enable/disable signal close to the install we first try
    ``<install_root>/plugin_enablement.json`` if it exists, then fall back to
    the p101 default. Failures degrade to "treat everything as enabled".
    """
    local = root / "plugin_enablement.json"
    if local.exists():
        return PluginEnablementStore(local)
    try:
        return PluginEnablementStore(resolve_enablement_store_path(None))
    except PluginEnablementStoreError as exc:
        log.debug("Plugin runtime: no enablement store available: %s", exc)
        return None


def _is_enabled(store: PluginEnablementStore, name: str) -> bool:
    try:
        return bool(store.is_enabled(name))
    except PluginEnablementStoreError as exc:
        # Corrupt/unreadable store: default to enabled (p101's own default for
        # an absent entry), but don't let it crash loading.
        log.debug("Plugin runtime: enablement check failed for %r: %s", name, exc)
        return True


def _instantiate_plugin(name: str, installed_path: Path) -> Any | None:
    """Import an installed plugin and return an instance, or None on any failure."""
    module = _import_plugin_module(name, installed_path)
    if module is None:
        return None
    instance = _instance_from_module(module)
    if instance is None:
        # The package __init__ had no entrypoint; scan its top-level modules.
        for sub in _iter_plugin_modules(name, installed_path):
            instance = _instance_from_module(sub)
            if instance is not None:
                break
    if instance is None:
        log.debug("Plugin runtime: %s exposes no recognizable entrypoint; skipping", name)
    return instance


def _import_plugin_module(name: str, installed_path: Path) -> Any | None:
    """Import the plugin's package ``__init__.py`` (or a single-file module)."""
    if installed_path.is_dir():
        init_file = installed_path / "__init__.py"
        if not init_file.is_file():
            return None
        return _import_from_file(name, init_file, package_dir=installed_path)
    if installed_path.is_file() and installed_path.suffix == ".py":
        return _import_from_file(name, installed_path)
    return None


def _iter_plugin_modules(name: str, installed_path: Path) -> list[Any]:
    """Best-effort import of each top-level ``.py`` in a plugin package."""
    if not installed_path.is_dir():
        return []
    modules: list[Any] = []
    for py_file in sorted(installed_path.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        mod = _import_from_file(f"{name}.{py_file.stem}", py_file, package_dir=installed_path)
        if mod is not None:
            modules.append(mod)
    return modules


def _import_from_file(unique_suffix: str, file_path: Path, *, package_dir: Path | None = None) -> Any | None:
    """Import a module from a file path under a synthetic, collision-safe name."""
    safe = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in unique_suffix)
    module_name = f"_thomas_plugin_runtime_{safe}_{abs(hash(str(file_path))) & 0xFFFFFFFF:x}"
    try:
        if package_dir is not None:
            spec = importlib.util.spec_from_file_location(
                module_name,
                str(file_path),
                submodule_search_locations=[str(package_dir)],
            )
        else:
            spec = importlib.util.spec_from_file_location(module_name, str(file_path))
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)  # type: ignore[union-attr]
        except BaseException as exc:  # REVIEWED: isolate ANY plugin import-time failure
            sys.modules.pop(module_name, None)
            log.debug("Plugin runtime: import of %s failed: %s", file_path, exc)
            return None
        return module
    except BaseException as exc:  # REVIEWED: never let plugin loading break a turn
        log.debug("Plugin runtime: unexpected error importing %s: %s", file_path, exc)
        return None


def _instance_from_module(module: Any) -> Any | None:
    """Obtain a plugin instance from a module's recognized entrypoints."""
    for func_name in _ENTRYPOINT_FUNCS:
        func = getattr(module, func_name, None)
        if callable(func):
            try:
                instance = func()
            except BaseException as exc:  # REVIEWED: isolate entrypoint failures
                log.debug("Plugin runtime: %s() raised: %s", func_name, exc)
                continue
            if instance is not None:
                return instance
    for attr_name in _ENTRYPOINT_ATTRS:
        instance = getattr(module, attr_name, None)
        # A module-level PLUGIN may legitimately be a dict descriptor (e.g.
        # p105/p100). Those are not hookable instances, but run_hook tolerates
        # them (it just finds no hook callable), so we accept any non-None,
        # non-callable object here and let the hook runner decide.
        if instance is not None and not isinstance(instance, type):
            return instance
    return None


__all__ = ["get_enabled_plugin_instances", "clear_cache", "MANIFEST_FILENAME"]
