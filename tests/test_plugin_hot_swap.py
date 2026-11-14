"""Phase 3.5: the proof, done the way it would actually be used.

`plans/thomas/tasks/PRAXIS-PHASE3-KERNEL/PLAN.md`.

A real plugin package is written to disk, mounted, and dispatched through the
same ``make_plugin_hook_runner`` a turn uses. Then its source file is *edited*
while the process keeps running, and the next dispatch shows the new behaviour.
No restart, no new interpreter, no reimport by the test — the supervisor does
it, because that is what has to work.

The failure this pins down is specific and was real: plugin instances were
cached against the mtime of ``installed_plugins.json``, which does not change
when you edit a plugin. Saving a fix and seeing nothing happen was not a stale
process; nothing in the cache key looked at the file that changed.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from thomas.agent.kernel_wiring import default_kernel
from thomas.core.kernel import SwapError
from thomas.server.plugin_hook_bridge import make_plugin_hook_runner
from thomas.server.plugin_kernel_mount import INSTALLED_PLUGINS_MOUNTED
from thomas.server.plugin_supervisor import PluginSupervisor

_PLUGIN_SOURCE = """
class Plugin:
    name = "{name}"

    def before_tool(self, payload):
        data = dict(payload or {{}})
        data.setdefault("marks", [])
        data["marks"] = list(data["marks"]) + ["{mark}"]
        return data


def get_plugin():
    return Plugin()
"""

_BROKEN_SOURCE = """
raise ValueError("this edit does not import")
"""


def _write_plugin(root: Path, name: str, mark: str, *, broken: bool = False) -> Path:
    """Write (or rewrite) a plugin package on disk, exactly as an edit would."""
    package = root / name
    package.mkdir(parents=True, exist_ok=True)
    source = _BROKEN_SOURCE if broken else _PLUGIN_SOURCE.format(name=name, mark=mark)
    (package / "__init__.py").write_text(source, encoding="utf-8")
    return package


def _write_manifest(root: Path, *names: str) -> None:
    manifest = {"plugins": {name: {"installed_path": str(root / name)} for name in names}}
    (root / "installed_plugins.json").write_text(json.dumps(manifest), encoding="utf-8")


@pytest.fixture
def plugin_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An install root of our own, with an enablement store of our own."""
    monkeypatch.setenv("THOMAS_PLUGIN_ENABLEMENT_STORE", str(tmp_path / "enablement.json"))
    from thomas.plugins.runtime import clear_cache

    clear_cache()
    root = tmp_path / "plugins"
    root.mkdir()
    return root


def _marks(runner) -> list[str]:
    return list(asyncio.run(runner("before_tool", {})).get("marks", []))


def _supervised(root: Path) -> tuple[PluginSupervisor, object]:
    kernel = default_kernel()
    supervisor = PluginSupervisor(kernel=kernel, install_root=str(root)).start()
    return supervisor, make_plugin_hook_runner(install_root=str(root), kernel=kernel)


# ---------------------------------------------------------------------------
# the proof
# ---------------------------------------------------------------------------


def test_a_plugin_edited_on_disk_takes_effect_without_a_restart(plugin_root: Path) -> None:
    """Edit the file, sync, and the next hook call runs the new code."""
    _write_plugin(plugin_root, "demo_stamp", "v1")
    _write_manifest(plugin_root, "demo_stamp")

    supervisor, runner = _supervised(plugin_root)
    assert _marks(runner) == ["v1"]

    # The self-edit. Same process, same kernel, same runner object.
    _write_plugin(plugin_root, "demo_stamp", "v2")
    changes = supervisor.sync()

    assert changes["reloaded"] == ["demo_stamp"]
    assert _marks(runner) == ["v2"]


def test_reloading_one_plugin_by_name_swaps_just_that_one(plugin_root: Path) -> None:
    _write_plugin(plugin_root, "demo_stamp", "v1")
    _write_plugin(plugin_root, "other_stamp", "other")
    _write_manifest(plugin_root, "demo_stamp", "other_stamp")

    supervisor, runner = _supervised(plugin_root)
    assert sorted(_marks(runner)) == ["other", "v1"]

    _write_plugin(plugin_root, "demo_stamp", "v2")
    assert supervisor.reload("demo_stamp") == "reloaded"

    assert sorted(_marks(runner)) == ["other", "v2"]


def test_a_reload_with_nothing_changed_says_unchanged(plugin_root: Path) -> None:
    """Told apart from a reload that did nothing because it broke."""
    _write_plugin(plugin_root, "demo_stamp", "v1")
    _write_manifest(plugin_root, "demo_stamp")

    supervisor, runner = _supervised(plugin_root)

    assert supervisor.reload("demo_stamp") == "unchanged"
    assert supervisor.reload("demo_stamp", force=True) == "reloaded"
    assert _marks(runner) == ["v1"]


def test_a_broken_edit_leaves_the_previous_version_answering(plugin_root: Path) -> None:
    """The edit that does not import must not take the plugin down with it."""
    _write_plugin(plugin_root, "demo_stamp", "v1")
    _write_manifest(plugin_root, "demo_stamp")

    supervisor, runner = _supervised(plugin_root)
    _write_plugin(plugin_root, "demo_stamp", "v2", broken=True)

    assert supervisor.reload("demo_stamp") == "failed"
    assert _marks(runner) == ["v1"]
    assert supervisor.mounted_names() == ["demo_stamp"]

    # ...and the fix lands without any further intervention.
    _write_plugin(plugin_root, "demo_stamp", "v3")
    assert supervisor.reload("demo_stamp") == "reloaded"
    assert _marks(runner) == ["v3"]


def test_an_edit_that_imports_but_will_not_mount_is_still_retried(
    plugin_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fingerprint names the version answering, on every path that can fail.

    New code can import cleanly and still fail to go on the bus. Recording that
    version's fingerprint anyway would make the next reload of the same file
    answer ``unchanged`` — "what is on disk is already running" — about code that
    never mounted, and the old version would keep answering unremarked.
    """
    import thomas.server.plugin_supervisor as supervisor_module

    _write_plugin(plugin_root, "demo_stamp", "v1")
    _write_manifest(plugin_root, "demo_stamp")
    supervisor, runner = _supervised(plugin_root)

    refusing = True
    real_swap = supervisor_module.swap

    def maybe_swap(fork, new_plugin, config=None):
        if refusing:
            raise SwapError("the kernel refused the mount", restored=True, fork=fork)
        return real_swap(fork, new_plugin, config)

    monkeypatch.setattr(supervisor_module, "swap", maybe_swap)
    _write_plugin(plugin_root, "demo_stamp", "v2")

    assert supervisor.reload("demo_stamp") == "failed"
    assert _marks(runner) == ["v1"]

    refusing = False
    assert supervisor.reload("demo_stamp") == "reloaded"
    assert _marks(runner) == ["v2"]


# ---------------------------------------------------------------------------
# unplug and replug
# ---------------------------------------------------------------------------


def test_unplugging_one_plugin_leaves_the_others_running(plugin_root: Path) -> None:
    _write_plugin(plugin_root, "demo_stamp", "v1")
    _write_plugin(plugin_root, "other_stamp", "other")
    _write_manifest(plugin_root, "demo_stamp", "other_stamp")

    supervisor, runner = _supervised(plugin_root)

    assert supervisor.unplug("demo_stamp") is True
    assert _marks(runner) == ["other"]
    assert supervisor.unplugged_names() == ["demo_stamp"]

    assert supervisor.replug("demo_stamp") is True
    assert sorted(_marks(runner)) == ["other", "v1"]


def test_unplugging_something_already_off_is_not_an_error(plugin_root: Path) -> None:
    _write_plugin(plugin_root, "demo_stamp", "v1")
    _write_manifest(plugin_root, "demo_stamp")

    supervisor, _ = _supervised(plugin_root)

    assert supervisor.unplug("demo_stamp") is True
    assert supervisor.unplug("demo_stamp") is False
    assert supervisor.unplug("never_installed") is False


def test_a_replug_runs_the_code_as_it_is_now_not_as_it_was(plugin_root: Path) -> None:
    """Between the unplug and the replug, the file changed. The new one wins."""
    _write_plugin(plugin_root, "demo_stamp", "v1")
    _write_manifest(plugin_root, "demo_stamp")

    supervisor, runner = _supervised(plugin_root)
    supervisor.unplug("demo_stamp")
    _write_plugin(plugin_root, "demo_stamp", "v2")

    assert supervisor.replug("demo_stamp") is True
    assert _marks(runner) == ["v2"]


def test_unplugging_everything_does_not_hand_the_lane_back_to_the_scan(plugin_root: Path) -> None:
    """The off switch must not turn itself off.

    ``plugin_hook_bridge`` falls back to a per-call manifest scan when the mount
    marker is absent. If unplugging the last plugin dropped the marker, that
    scan would load the unplugged plugin straight off disk and run it again.
    """
    _write_plugin(plugin_root, "demo_stamp", "v1")
    _write_manifest(plugin_root, "demo_stamp")

    supervisor, runner = _supervised(plugin_root)
    supervisor.unplug("demo_stamp")

    assert supervisor.kernel.root.has(INSTALLED_PLUGINS_MOUNTED)
    assert _marks(runner) == []

    supervisor.dispose()
    assert not supervisor.kernel.root.has(INSTALLED_PLUGINS_MOUNTED)
