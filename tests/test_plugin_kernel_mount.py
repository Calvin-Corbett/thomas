"""Phase 3.3: the plugin runtime lives on the kernel, and the rest says so.

`plans/thomas/tasks/PRAXIS-PHASE3-KERNEL/PLAN.md`.

Three properties:

1. A legacy plugin, mounted, behaves exactly as it did through ``run_hook`` —
   same hook lookup, same argument conventions — and unmounting removes it.
2. Dispatch does not double-fire. Mounted hooks come from the bus; the legacy
   per-call scan stands down while the mount marker is present and returns the
   moment it is gone.
3. The systems report tells the truth about what each one is. The spec called
   them "four plugin systems"; three of them have no hook dispatch at all, and
   believing otherwise is how a catalog gets mistaken for a running feature.
"""

from __future__ import annotations

import asyncio

import pytest

from thomas.agent.kernel_wiring import default_kernel
from thomas.server.plugin_hook_bridge import make_plugin_hook_runner
from thomas.server.plugin_kernel_mount import (
    INSTALLED_PLUGINS_MOUNTED,
    MountedLegacyPlugin,
    plugin_systems_report,
)
from thomas.server.plugin_supervisor import start_plugin_supervisor


class StampingPlugin:
    """A plugin shaped like the bundled packs: takes a payload, returns it changed."""

    name = "stamper"

    def before_tool(self, payload):
        data = dict(payload or {})
        data.setdefault("stamped_by", self.name)
        return data


class QuietPlugin:
    """Installed, enabled, and implements nothing."""

    name = "quiet"


def _mount(kernel, instances):
    """Mount specific instances and claim the hook lane; return the way back.

    The supervisor mounts from an install root on disk, and these tests are about
    the adapter, the marker and the report — so they mount instances directly.
    The supervisor's own mounting is covered in ``test_plugin_supervisor_sync.py``
    and ``test_plugin_hot_swap.py``.
    """
    forks = [kernel.mount(MountedLegacyPlugin(instance)) for instance in instances]
    marker = kernel.root.set(INSTALLED_PLUGINS_MOUNTED, True)

    def unmount() -> None:
        marker()
        for fork in reversed(forks):
            fork.dispose()

    return unmount


# ---------------------------------------------------------------------------
# the adapter
# ---------------------------------------------------------------------------


def test_the_adapter_finds_the_hooks_a_plugin_implements() -> None:
    adapter = MountedLegacyPlugin(StampingPlugin())
    assert adapter.name
    assert "before_tool" in adapter.hooks


def test_a_plugin_that_implements_nothing_has_no_hooks() -> None:
    assert MountedLegacyPlugin(QuietPlugin()).hooks == ()


def test_a_mounted_plugins_hook_runs_and_its_return_reaches_the_caller() -> None:
    kernel = default_kernel()
    _mount(kernel, [StampingPlugin()])

    runner = make_plugin_hook_runner(install_root="__none__", kernel=kernel)
    out = asyncio.run(runner("before_tool", {"tool": "read"}))

    assert out == {"tool": "read", "stamped_by": "stamper"}


def test_unmounting_removes_the_plugins_hooks() -> None:
    kernel = default_kernel()
    unmount = _mount(kernel, [StampingPlugin()])
    runner = make_plugin_hook_runner(install_root="__none__", kernel=kernel)
    assert "stamped_by" in asyncio.run(runner("before_tool", {}))

    unmount()

    assert asyncio.run(runner("before_tool", {})) == {}
    assert not kernel.root.has(INSTALLED_PLUGINS_MOUNTED)


def test_a_plugin_contributing_nothing_is_reported_not_hidden() -> None:
    """Installed and enabled reads like doing something. For these it is not."""
    kernel = default_kernel()
    _mount(kernel, [StampingPlugin(), QuietPlugin()])

    installed = plugin_systems_report(kernel=kernel)["installed_plugins"]

    assert installed["contributing_no_hooks"] == ["quiet"]
    assert set(installed["plugins"]) == {"stamper", "quiet"}


# ---------------------------------------------------------------------------
# dispatch fires once
# ---------------------------------------------------------------------------


def test_a_mounted_hook_fires_exactly_once() -> None:
    """The regression this guards: bus dispatch PLUS the legacy scan = twice."""
    calls: list[int] = []

    class Counter:
        name = "counter"

        def before_tool(self, payload):
            calls.append(1)
            return dict(payload or {})

    kernel = default_kernel()
    _mount(kernel, [Counter()])

    asyncio.run(make_plugin_hook_runner(install_root="__none__", kernel=kernel)("before_tool", {}))

    assert calls == [1]


def test_the_marker_gates_the_legacy_scan() -> None:
    kernel = default_kernel()
    assert not kernel.root.has(INSTALLED_PLUGINS_MOUNTED)

    unmount = _mount(kernel, [StampingPlugin()])
    assert kernel.root.has(INSTALLED_PLUGINS_MOUNTED)

    unmount()
    assert not kernel.root.has(INSTALLED_PLUGINS_MOUNTED)


def test_mounting_an_empty_install_root_still_marks_and_unwinds() -> None:
    """Nothing installed is not the same as nobody holding the lane."""
    kernel = default_kernel()
    supervisor = start_plugin_supervisor(kernel=kernel, install_root="")

    assert supervisor.mounted_names() == []
    assert kernel.root.has(INSTALLED_PLUGINS_MOUNTED)

    supervisor.dispose()
    assert not kernel.root.has(INSTALLED_PLUGINS_MOUNTED)


# ---------------------------------------------------------------------------
# the report tells the truth
# ---------------------------------------------------------------------------


def test_the_report_names_the_extension_packs_as_catalog_only() -> None:
    """Pins the finding: nothing in the repo ever loads pack code.

    extension_catalog_runtime checks that hooks.py EXISTS and never imports it.
    If someone later gives the packs a runtime, this test should fail and be
    updated deliberately — not drift.
    """
    report = plugin_systems_report(kernel=default_kernel())

    packs = report["extension_packs"]
    assert packs["kind"] == "catalog-only"
    assert packs["hooks_execute"] is False


def test_the_report_calls_the_installers_installers() -> None:
    report = plugin_systems_report(kernel=default_kernel())

    assert report["agent_plugins"]["kind"] == "installer"
    assert report["desktop_plugins"]["kind"] == "installer"


def test_the_report_shows_the_runtime_moving_onto_the_kernel() -> None:
    kernel = default_kernel()

    before = plugin_systems_report(kernel=kernel)["installed_plugins"]
    assert before["mounted_on_kernel"] is False
    assert before["plugins"] == []

    unmount = _mount(kernel, [StampingPlugin(), QuietPlugin()])
    after = plugin_systems_report(kernel=kernel)["installed_plugins"]

    assert after["kind"] == "runtime"
    assert after["mounted_on_kernel"] is True
    assert set(after["plugins"]) == {"stamper", "quiet"}
    assert after["contributing_no_hooks"] == ["quiet"]

    unmount()
    assert plugin_systems_report(kernel=kernel)["installed_plugins"]["plugins"] == []


@pytest.mark.parametrize("hook", ["before_tool", "tool_pre"])
def test_the_adapter_covers_canonical_and_legacy_names(hook: str) -> None:
    """A pack subscribing to either spelling must still be reachable."""
    from thomas.server.plugin_kernel_mount import ALL_HOOK_NAMES

    assert hook in ALL_HOOK_NAMES
