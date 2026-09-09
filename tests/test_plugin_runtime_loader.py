"""Unit tests for thomas.plugins.runtime.get_enabled_plugin_instances.

Verifies the loader reads the installed-plugins manifest (p102 format),
honors the enable/disable state store (p101 format), instantiates plugins via
their entrypoints, and ISOLATES failures (a broken plugin is skipped, never
raised) — the core safety property for wiring hooks into a live turn.
"""

from __future__ import annotations

import json
from pathlib import Path

from thomas.plugins import runtime


def _write_manifest(root: Path, plugins: dict) -> None:
    (root / runtime.MANIFEST_FILENAME).write_text(
        json.dumps({"version": 1, "plugins": plugins}, indent=2),
        encoding="utf-8",
    )


def _make_plugin_package(root: Path, name: str, init_body: str) -> Path:
    pkg = root / name
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text(init_body, encoding="utf-8")
    return pkg


_GOOD_PLUGIN = """
class _StubPlugin:
    plugin_id = "stub-good"
    def before_tool(self, payload):
        return {"seen": payload}

def get_plugin():
    return _StubPlugin()
"""

_BROKEN_PLUGIN = """
raise RuntimeError("boom: this plugin fails to import")
"""

_CREATE_PLUGIN = """
class _StubCreatePlugin:
    plugin_id = "stub-create"

def create_plugin():
    return _StubCreatePlugin()
"""


def test_returns_enabled_instance(tmp_path: Path) -> None:
    runtime.clear_cache()
    root = tmp_path / "plugins"
    pkg = _make_plugin_package(root, "good_plugin", _GOOD_PLUGIN)
    _write_manifest(root, {"good_plugin": {"installed_path": str(pkg)}})

    instances = runtime.get_enabled_plugin_instances(root)

    assert len(instances) == 1
    assert getattr(instances[0], "plugin_id", None) == "stub-good"


def test_broken_plugin_is_skipped_not_raised(tmp_path: Path) -> None:
    runtime.clear_cache()
    root = tmp_path / "plugins"
    good_pkg = _make_plugin_package(root, "good_plugin", _GOOD_PLUGIN)
    broken_pkg = _make_plugin_package(root, "broken_plugin", _BROKEN_PLUGIN)
    _write_manifest(
        root,
        {
            "good_plugin": {"installed_path": str(good_pkg)},
            "broken_plugin": {"installed_path": str(broken_pkg)},
        },
    )

    # Must not raise even though one plugin explodes on import.
    instances = runtime.get_enabled_plugin_instances(root)

    ids = {getattr(i, "plugin_id", None) for i in instances}
    assert "stub-good" in ids
    assert "stub-create" not in ids  # not installed
    assert len(instances) == 1  # broken one skipped


def test_create_plugin_entrypoint(tmp_path: Path) -> None:
    runtime.clear_cache()
    root = tmp_path / "plugins"
    pkg = _make_plugin_package(root, "create_plugin_pkg", _CREATE_PLUGIN)
    _write_manifest(root, {"create_plugin_pkg": {"installed_path": str(pkg)}})

    instances = runtime.get_enabled_plugin_instances(root)

    assert len(instances) == 1
    assert getattr(instances[0], "plugin_id", None) == "stub-create"


def test_disabled_plugin_excluded(tmp_path: Path) -> None:
    runtime.clear_cache()
    root = tmp_path / "plugins"
    pkg = _make_plugin_package(root, "good_plugin", _GOOD_PLUGIN)
    _write_manifest(root, {"good_plugin": {"installed_path": str(pkg)}})

    # Co-locate an enablement store next to the install root marking the plugin
    # disabled (p101 schema_version=1 format).
    (root / "plugin_enablement.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "updated_at": 0,
                "plugins": {"good_plugin": {"enabled": False, "updated_at": 0}},
            }
        ),
        encoding="utf-8",
    )

    instances = runtime.get_enabled_plugin_instances(root)
    assert instances == []


def test_missing_manifest_returns_empty(tmp_path: Path) -> None:
    runtime.clear_cache()
    root = tmp_path / "no_plugins_here"
    root.mkdir()
    assert runtime.get_enabled_plugin_instances(root) == []


def test_none_root_returns_empty() -> None:
    runtime.clear_cache()
    assert runtime.get_enabled_plugin_instances(None) == []


def test_cache_invalidates_on_manifest_change(tmp_path: Path) -> None:
    runtime.clear_cache()
    root = tmp_path / "plugins"
    good_pkg = _make_plugin_package(root, "good_plugin", _GOOD_PLUGIN)
    _write_manifest(root, {"good_plugin": {"installed_path": str(good_pkg)}})

    first = runtime.get_enabled_plugin_instances(root)
    assert len(first) == 1

    # Add a second plugin and bump the manifest mtime.
    create_pkg = _make_plugin_package(root, "create_plugin_pkg", _CREATE_PLUGIN)
    import os
    import time

    _write_manifest(
        root,
        {
            "good_plugin": {"installed_path": str(good_pkg)},
            "create_plugin_pkg": {"installed_path": str(create_pkg)},
        },
    )
    # Force a distinct mtime so the cache key changes deterministically.
    future = time.time() + 10
    os.utime(root / runtime.MANIFEST_FILENAME, (future, future))

    second = runtime.get_enabled_plugin_instances(root)
    assert len(second) == 2
