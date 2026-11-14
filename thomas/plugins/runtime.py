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
- Results are cached per resolved install-root (keyed by absolute path, the
  manifest's mtime, and a fingerprint of the plugins' own source) so repeated
  turns don't re-import every plugin, while an edit to a plugin's code does
  invalidate the entry. Keying on the manifest alone meant saving a change to a
  plugin had no effect until the process restarted: nothing in the cache key
  looked at the file that changed.
- A plugin instance is obtained from the FIRST recognizable entrypoint:
  ``get_plugin()`` -> ``create_plugin()`` -> module-level ``PLUGIN``. This
  matches the real entrypoints exposed by p109..p112.

Why file-based import (not dotted import): installed plugins live under
``<install_root>/<name>/`` which is generally NOT on ``sys.path``. We import
each plugin package from its ``__init__.py`` using ``importlib.util``; if the
package ``__init__`` exposes no entrypoint we scan its top-level ``.py`` modules
for one. This mirrors the discovery approach in p100.

Every import here goes through ``thomas/plugins/source_loader.py``, which reads
the source and never a ``.pyc``. The default loader reuses cached bytecode when
the source's mtime *in whole seconds* and its size both match — the exact shape of
an agent rewriting its own plugin — and the reload would then report success
while the previous version kept answering.
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
from thomas.plugins.source_fingerprint import purge_imported_modules, source_fingerprint
from thomas.plugins.source_loader import register_source_only_prefix, source_only_spec

log = logging.getLogger(__name__)

MANIFEST_FILENAME = "installed_plugins.json"

# Entrypoints we recognize on a plugin module, in priority order.
_ENTRYPOINT_FUNCS = ("get_plugin", "create_plugin")
_ENTRYPOINT_ATTRS = ("PLUGIN", "plugin")

# Cache: resolved-install-root -> ((manifest_mtime, source_fingerprint), [instances])
_CACHE: dict[str, tuple[tuple[float, str], list[Any]]] = {}
_CACHE_LOCK = threading.Lock()


def get_enabled_plugin_instances(install_root: str | Path | None) -> list[Any]:
    """Return live instances for every *enabled* installed plugin.

    Args:
        install_root: Directory containing ``installed_plugins.json`` and the
            installed plugin packages. If ``None``/empty, returns ``[]`` (there
            is nothing to load).

    Returns:
        A list of plugin instances (possibly empty). Never raises.

    Cost: a cache hit now reads the plugins' ``.py`` files to fingerprint them
    rather than doing a single ``stat`` on the manifest. That is the price of an
    edit taking effect, it is bounded (see ``source_fingerprint``), and it is
    trivial in the common case of an empty or absent install root. The server
    does not pay it per hook at all — it mounts the plugins under the supervisor,
    which fingerprints only when asked to reload.
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

    # The source fingerprint is the half of this key that makes a self-edit
    # take effect: the manifest does not change when a plugin's own code does.
    stamp = (manifest_mtime, source_fingerprint(root))
    cache_key = str(root)
    with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
        if cached is not None and cached[0] == stamp:
            return list(cached[1])

    instances = _load_enabled_instances(root, manifest_path)

    with _CACHE_LOCK:
        _CACHE[cache_key] = (stamp, list(instances))
    return list(instances)


def clear_cache() -> None:
    """Drop the cached plugin instances (test/util helper)."""
    with _CACHE_LOCK:
        _CACHE.clear()


def enabled_plugin_paths(install_root: str | Path | None) -> dict[str, Path]:
    """Name -> installed directory, for every enabled plugin. Imports nothing.

    The cheap half of loading. A supervisor deciding what to mount, unmount or
    reload needs the names and the paths on disk; importing every plugin to find
    out which ones it already has mounted would defeat the point.
    """
    if not install_root:
        return {}
    try:
        root = Path(install_root).expanduser().resolve()
    except (OSError, ValueError, RuntimeError) as exc:  # REVIEWED: isolate path errors
        log.debug("Plugin runtime: invalid install_root %r: %s", install_root, exc)
        return {}
    return _enabled_paths(root, root / MANIFEST_FILENAME)


def load_plugin_instance(name: str, installed_path: str | Path, *, errors: list[str] | None = None) -> Any | None:
    """Import one plugin from disk right now, bypassing the cache.

    This is the reload path: it re-executes the package from its files and
    clears any submodules the previous load left in ``sys.modules``, so what
    comes back reflects the code that is on disk at this moment. Returns
    ``None`` rather than raising, like every other loader here.

    ``errors``, when given, collects why the load produced nothing. Never
    raising is right for a turn, which must not die over a plugin — but a reload
    has to tell you *why* your edit did not land, and without this the only
    sentence available was "no recognizable entrypoint", which is the wrong
    reason for a file that has a typo in it.
    """
    return _instantiate_plugin(name, Path(installed_path), errors=errors)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _enabled_paths(root: Path, manifest_path: Path) -> dict[str, Path]:
    """The manifest read, the enablement store applied, nothing imported."""
    manifest = _read_manifest(manifest_path)
    if not manifest:
        return {}

    plugins_map = manifest.get("plugins")
    if not isinstance(plugins_map, dict):
        return {}

    store = _enablement_store(root)

    paths: dict[str, Path] = {}
    for name in sorted(plugins_map.keys()):
        entry = plugins_map.get(name)
        if not isinstance(entry, dict):
            continue

        if store is not None and not _is_enabled(store, name):
            continue

        paths[name] = Path(entry.get("installed_path") or str(root / name))

    return paths


def _load_enabled_instances(root: Path, manifest_path: Path) -> list[Any]:
    instances: list[Any] = []
    for name, installed_path in _enabled_paths(root, manifest_path).items():
        instance = _instantiate_plugin(name, installed_path)
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


def _note(errors: list[str] | None, reason: str) -> None:
    """Record why a load produced nothing, when the caller asked to be told."""
    if errors is not None:
        errors.append(reason)


def _instantiate_plugin(name: str, installed_path: Path, *, errors: list[str] | None = None) -> Any | None:
    """Import an installed plugin and return an instance, or None on any failure."""
    module = _import_plugin_module(name, installed_path, errors=errors)
    if module is None:
        return None
    instance = _instance_from_module(module, errors=errors)
    if instance is None:
        # The package __init__ had no entrypoint; scan its top-level modules.
        for sub in _iter_plugin_modules(name, installed_path, errors=errors):
            instance = _instance_from_module(sub, errors=errors)
            if instance is not None:
                break
    if instance is None:
        log.debug("Plugin runtime: %s exposes no recognizable entrypoint; skipping", name)
    return instance


def _import_plugin_module(name: str, installed_path: Path, *, errors: list[str] | None = None) -> Any | None:
    """Import the plugin's package ``__init__.py`` (or a single-file module)."""
    if installed_path.is_dir():
        init_file = installed_path / "__init__.py"
        if not init_file.is_file():
            _note(errors, f"{installed_path.name} has no __init__.py")
            return None
        return _import_from_file(name, init_file, package_dir=installed_path, errors=errors)
    if installed_path.is_file() and installed_path.suffix == ".py":
        return _import_from_file(name, installed_path, errors=errors)
    _note(errors, f"{installed_path} is not a plugin package or a .py file")
    return None


def _iter_plugin_modules(name: str, installed_path: Path, *, errors: list[str] | None = None) -> list[Any]:
    """Best-effort import of each top-level ``.py`` in a plugin package."""
    if not installed_path.is_dir():
        return []
    modules: list[Any] = []
    for py_file in sorted(installed_path.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        mod = _import_from_file(f"{name}.{py_file.stem}", py_file, package_dir=installed_path, errors=errors)
        if mod is not None:
            modules.append(mod)
    return modules


def _import_from_file(
    unique_suffix: str,
    file_path: Path,
    *,
    package_dir: Path | None = None,
    errors: list[str] | None = None,
) -> Any | None:
    """Import a module from a file path under a synthetic, collision-safe name."""
    safe = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in unique_suffix)
    module_name = f"_thomas_plugin_runtime_{safe}_{abs(hash(str(file_path))) & 0xFFFFFFFF:x}"
    try:
        # Source only, never __pycache__. The default loader reuses cached
        # bytecode when the source's mtime-in-seconds and size both match, which
        # an edit made within a second of the last load satisfies routinely: the
        # reload then reports success while the previous version keeps running.
        # See thomas/plugins/source_loader.py. Registering the prefix first is
        # what extends that to a `from . import rule` inside the package.
        register_source_only_prefix(module_name)
        spec = source_only_spec(module_name, file_path, package_dir=package_dir)
        if spec is None or spec.loader is None:
            _note(errors, f"{file_path.name} could not be loaded as a module")
            return None
        # A previous load of this same file left the package AND its submodules
        # in sys.modules under this name. Re-executing __init__ without clearing
        # them re-binds the cached submodules, so an edit inside a submodule
        # would "reload" into the old behaviour — silently, and reported as a
        # success. Clear them first; the re-exec below repopulates what it uses.
        purge_imported_modules(module_name)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)  # type: ignore[union-attr]
        except BaseException as exc:  # REVIEWED: isolate ANY plugin import-time failure
            sys.modules.pop(module_name, None)
            log.debug("Plugin runtime: import of %s failed: %s", file_path, exc)
            _note(errors, f"{type(exc).__name__}: {exc}")
            return None
        return module
    except BaseException as exc:  # REVIEWED: never let plugin loading break a turn
        log.debug("Plugin runtime: unexpected error importing %s: %s", file_path, exc)
        _note(errors, f"{type(exc).__name__}: {exc}")
        return None


def _instance_from_module(module: Any, *, errors: list[str] | None = None) -> Any | None:
    """Obtain a plugin instance from a module's recognized entrypoints."""
    for func_name in _ENTRYPOINT_FUNCS:
        func = getattr(module, func_name, None)
        if callable(func):
            try:
                instance = func()
            except BaseException as exc:  # REVIEWED: isolate entrypoint failures
                log.debug("Plugin runtime: %s() raised: %s", func_name, exc)
                _note(errors, f"{func_name}() raised {type(exc).__name__}: {exc}")
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


__all__ = [
    "MANIFEST_FILENAME",
    "clear_cache",
    "enabled_plugin_paths",
    "get_enabled_plugin_instances",
    "load_plugin_instance",
]
