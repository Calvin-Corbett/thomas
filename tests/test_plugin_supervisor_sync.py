"""Phase 3.5: picking up what changed on disk, and only what changed.

`plans/thomas/tasks/PRAXIS-PHASE3-KERNEL/PLAN.md`.

``sync`` is the operation a running Thomas performs on itself: mount what was
installed since, drop what was removed, reload what was edited, and leave alone
what somebody deliberately switched off. The cache fix underneath it is pinned
here too, because it is the reason an edit used to do nothing at all.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from thomas.agent.kernel_wiring import default_kernel
from thomas.server.plugin_hook_bridge import make_plugin_hook_runner
from thomas.server.plugin_supervisor import PluginSupervisor

_SOURCE = """
class Plugin:
    name = "{name}"

    def before_tool(self, payload):
        data = dict(payload or {{}})
        data["marks"] = list(data.get("marks") or []) + ["{mark}"]
        return data


def get_plugin():
    return Plugin()
"""

# A package whose behaviour lives in a submodule — the case a naive reload gets
# wrong by re-binding the cached submodule and reporting success.
_PACKAGE_INIT = """
from . import rule


class Plugin:
    name = "{name}"

    def before_tool(self, payload):
        data = dict(payload or {{}})
        data["marks"] = list(data.get("marks") or []) + [rule.MARK]
        return data


def get_plugin():
    return Plugin()
"""


def _write_plugin(root: Path, name: str, mark: str) -> None:
    package = root / name
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text(_SOURCE.format(name=name, mark=mark), encoding="utf-8")


def _write_package_with_submodule(root: Path, name: str, mark: str) -> None:
    package = root / name
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text(_PACKAGE_INIT.format(name=name), encoding="utf-8")
    (package / "rule.py").write_text(f'MARK = "{mark}"\n', encoding="utf-8")


def _write_manifest(root: Path, *names: str) -> None:
    manifest = {"plugins": {name: {"installed_path": str(root / name)} for name in names}}
    (root / "installed_plugins.json").write_text(json.dumps(manifest), encoding="utf-8")


@pytest.fixture
def plugin_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("THOMAS_PLUGIN_ENABLEMENT_STORE", str(tmp_path / "enablement.json"))
    from thomas.plugins.runtime import clear_cache

    clear_cache()
    root = tmp_path / "plugins"
    root.mkdir()
    return root


def _supervised(root: Path) -> tuple[PluginSupervisor, object]:
    kernel = default_kernel()
    supervisor = PluginSupervisor(kernel=kernel, install_root=str(root)).start()
    return supervisor, make_plugin_hook_runner(install_root=str(root), kernel=kernel)


def _marks(runner) -> list[str]:
    return sorted(asyncio.run(runner("before_tool", {})).get("marks", []))


# ---------------------------------------------------------------------------
# sync
# ---------------------------------------------------------------------------


def test_sync_mounts_a_plugin_installed_while_thomas_was_running(plugin_root: Path) -> None:
    _write_plugin(plugin_root, "first_plugin", "first")
    _write_manifest(plugin_root, "first_plugin")

    supervisor, runner = _supervised(plugin_root)
    assert _marks(runner) == ["first"]

    _write_plugin(plugin_root, "second_plugin", "second")
    _write_manifest(plugin_root, "first_plugin", "second_plugin")

    assert supervisor.sync()["mounted"] == ["second_plugin"]
    assert _marks(runner) == ["first", "second"]


def test_sync_unmounts_a_plugin_that_was_uninstalled(plugin_root: Path) -> None:
    _write_plugin(plugin_root, "first_plugin", "first")
    _write_plugin(plugin_root, "second_plugin", "second")
    _write_manifest(plugin_root, "first_plugin", "second_plugin")

    supervisor, runner = _supervised(plugin_root)
    assert _marks(runner) == ["first", "second"]

    _write_manifest(plugin_root, "first_plugin")

    assert supervisor.sync()["unmounted"] == ["second_plugin"]
    assert _marks(runner) == ["first"]
    assert supervisor.mounted_names() == ["first_plugin"]


def test_sync_does_not_overrule_a_deliberate_unplug(plugin_root: Path) -> None:
    """An off switch a disk scan can flip back on is not an off switch."""
    _write_plugin(plugin_root, "first_plugin", "first")
    _write_manifest(plugin_root, "first_plugin")

    supervisor, runner = _supervised(plugin_root)
    supervisor.unplug("first_plugin")

    report = supervisor.sync()

    assert report["mounted"] == []
    assert report["reloaded"] == []
    assert _marks(runner) == []
    assert supervisor.unplugged_names() == ["first_plugin"]


def test_sync_reports_a_plugin_whose_new_code_will_not_load(plugin_root: Path) -> None:
    _write_plugin(plugin_root, "first_plugin", "first")
    _write_manifest(plugin_root, "first_plugin")

    supervisor, runner = _supervised(plugin_root)
    (plugin_root / "first_plugin" / "__init__.py").write_text("raise ValueError('broken')\n", encoding="utf-8")

    assert supervisor.sync()["failed"] == ["first_plugin"]
    assert _marks(runner) == ["first"]


def test_a_still_broken_edit_keeps_saying_failed(plugin_root: Path) -> None:
    """Asking twice about the same broken file must not answer ``unchanged``.

    ``unchanged`` means "the code on disk is already what is running". Recording
    the fingerprint of code that failed to import would make the second reload
    say exactly that about an edit that never loaded — and the plugin answering
    would still be the old one.
    """
    _write_plugin(plugin_root, "first_plugin", "first")
    _write_manifest(plugin_root, "first_plugin")

    supervisor, runner = _supervised(plugin_root)
    (plugin_root / "first_plugin" / "__init__.py").write_text("raise ValueError('broken')\n", encoding="utf-8")

    assert supervisor.reload("first_plugin") == "failed"
    assert supervisor.reload("first_plugin") == "failed"
    assert supervisor.sync()["failed"] == ["first_plugin"]
    assert _marks(runner) == ["first"]

    _write_plugin(plugin_root, "first_plugin", "fixed")
    assert supervisor.reload("first_plugin") == "reloaded"
    assert _marks(runner) == ["fixed"]


@pytest.mark.parametrize(
    ("broken_source", "expected"),
    [
        ("raise ValueError('typo in my edit')\n", "ValueError: typo in my edit"),
        ("def broken(:\n", "SyntaxError"),
    ],
)
def test_a_failed_reload_says_why_not_just_that_it_failed(
    plugin_root: Path,
    broken_source: str,
    expected: str,
) -> None:
    """The status row must name the real failure.

    The runtime loader never raises: it logs a plugin's own import error at
    debug and returns None. So the reason reaching the status surface was always
    "no recognizable plugin entrypoint on disk" — said about a file that has a
    plain entrypoint and a typo. That sentence sends you looking for the wrong
    thing, and it is the only sentence you get.
    """
    _write_plugin(plugin_root, "first_plugin", "first")
    _write_manifest(plugin_root, "first_plugin")

    supervisor, runner = _supervised(plugin_root)
    (plugin_root / "first_plugin" / "__init__.py").write_text(broken_source, encoding="utf-8")

    assert supervisor.reload("first_plugin") == "failed"

    row = {entry["name"]: entry for entry in supervisor.status()["plugins"]}["first_plugin"]
    assert expected in row["error"]
    # ...and the previous version is still the one answering.
    assert row["state"] == "mounted"
    assert _marks(runner) == ["first"]


def test_an_edit_inside_a_submodule_reloads_too(plugin_root: Path) -> None:
    """Without clearing sys.modules, the reload succeeds and changes nothing."""
    _write_package_with_submodule(plugin_root, "deep_plugin", "deep-v1")
    _write_manifest(plugin_root, "deep_plugin")

    supervisor, runner = _supervised(plugin_root)
    assert _marks(runner) == ["deep-v1"]

    (plugin_root / "deep_plugin" / "rule.py").write_text('MARK = "deep-v2"\n', encoding="utf-8")

    assert supervisor.reload("deep_plugin") == "reloaded"
    assert _marks(runner) == ["deep-v2"]


def test_the_status_surface_names_what_is_mounted_and_what_is_off(plugin_root: Path) -> None:
    _write_plugin(plugin_root, "first_plugin", "first")
    _write_plugin(plugin_root, "second_plugin", "second")
    _write_manifest(plugin_root, "first_plugin", "second_plugin")

    supervisor, _ = _supervised(plugin_root)
    supervisor.unplug("second_plugin")
    status = supervisor.status()

    assert status["supervised"] is True
    assert status["mounted"] == ["first_plugin"]
    assert status["unplugged"] == ["second_plugin"]
    rows = {row["name"]: row for row in status["plugins"]}
    assert rows["first_plugin"]["state"] == "mounted"
    assert rows["first_plugin"]["hooks"] == ["before_tool"]
    assert rows["second_plugin"]["state"] == "unplugged"


# ---------------------------------------------------------------------------
# the cache underneath
# ---------------------------------------------------------------------------


def test_the_loader_cache_no_longer_hides_an_edit(plugin_root: Path) -> None:
    """The defect itself, pinned below the supervisor.

    The cache was keyed on the manifest's mtime. Editing a plugin leaves that
    file untouched, so every later load returned the instance built from the
    code as it was at first load — for the life of the process.
    """
    from thomas.plugins.runtime import get_enabled_plugin_instances

    _write_plugin(plugin_root, "first_plugin", "first")
    _write_manifest(plugin_root, "first_plugin")

    before = get_enabled_plugin_instances(str(plugin_root))
    assert before[0].before_tool({})["marks"] == ["first"]

    _write_plugin(plugin_root, "first_plugin", "second")
    after = get_enabled_plugin_instances(str(plugin_root))

    assert after[0].before_tool({})["marks"] == ["second"]


def test_identical_code_is_not_reloaded(plugin_root: Path) -> None:
    """Fingerprinting content, not timestamps: a rewrite of the same bytes is
    not a change, and a change within the same second still is."""
    from thomas.plugins.runtime import get_enabled_plugin_instances

    _write_plugin(plugin_root, "first_plugin", "first")
    _write_manifest(plugin_root, "first_plugin")

    first = get_enabled_plugin_instances(str(plugin_root))
    _write_plugin(plugin_root, "first_plugin", "first")  # same bytes, new mtime
    second = get_enabled_plugin_instances(str(plugin_root))

    assert first[0] is second[0]
