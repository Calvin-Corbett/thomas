"""Phase 3.5: the other three plugin systems are kernel services now.

`plans/thomas/tasks/PRAXIS-PHASE3-KERNEL/PLAN.md`.

Phase 3.3 established that the catalog and the two installers dispatch no hooks,
so there was nothing to *remount*. What they do have is a callable surface, and
these tests hold it to the same three properties the runtime got: registered
reversibly, listed by name, and replaceable while Thomas runs.

The desktop installer test is the one that matters most, because it proves the
seam is on the path a real install takes: the marketplace import route imports
``install_plugin_bundle_bytes`` from ``thomas/server/desktop_plugins``, and that
name now resolves the kernel service.
"""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any

import pytest

from thomas.agent.kernel_wiring import default_kernel, set_kernel
from thomas.server.plugin_systems_kernel import (
    AGENT_PLUGIN_INSTALLER,
    DESKTOP_PLUGIN_INSTALLER,
    EXTENSION_CATALOG,
    SYSTEM_SERVICES,
    AgentPluginInstaller,
    DesktopPluginInstaller,
    ExtensionCatalog,
    mount_plugin_systems,
    resolve_system,
)


class StubCatalog:
    """A replacement provider — what a swapped-in system looks like."""

    name = "stub-extensions"
    kind = "catalog"
    hooks_execute = False

    def packs(self, root: Any = None) -> list[Any]:
        return [{"id": "stub-pack"}]

    def describe(self) -> dict[str, Any]:
        return {"provider": "StubCatalog", "name": self.name, "kind": self.kind, "count": 1}


class RecordingInstaller:
    """Records what it was asked to install instead of touching the disk."""

    name = "recording"
    kind = "installer"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def install(self, config: Any, bundle_bytes: bytes, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"config": config, "bundle": bundle_bytes, **kwargs})
        return {"ok": True, "installed_by": self.name}

    def describe(self) -> dict[str, Any]:
        return {"provider": "RecordingInstaller", "name": self.name, "kind": self.kind}


@pytest.fixture
def process_kernel():
    """Own the process-wide kernel for the duration of one test."""
    kernel = default_kernel()
    set_kernel(kernel)
    try:
        yield kernel
    finally:
        set_kernel(None)


# ---------------------------------------------------------------------------
# mounted, listed, reversible
# ---------------------------------------------------------------------------


def test_all_three_systems_mount_as_kernel_services() -> None:
    kernel = default_kernel()
    mounted = mount_plugin_systems(kernel=kernel)

    for service in SYSTEM_SERVICES:
        assert kernel.root.has(service), f"{service} did not reach the kernel"
    assert set(mounted.names) == {f"system:{service}" for service in SYSTEM_SERVICES}


def test_unmounting_withdraws_every_service_it_registered() -> None:
    kernel = default_kernel()
    mounted = mount_plugin_systems(kernel=kernel)

    mounted.dispose()

    assert [service for service in SYSTEM_SERVICES if kernel.root.has(service)] == []
    assert kernel.mounted() == []


def test_resolving_without_a_mount_falls_back_to_the_default_provider() -> None:
    """These systems worked before the kernel; resolving must not require it."""
    kernel = default_kernel()

    provider = resolve_system(EXTENSION_CATALOG, kernel=kernel)

    assert isinstance(provider, ExtensionCatalog)


def test_resolving_with_a_mount_returns_the_mounted_provider() -> None:
    kernel = default_kernel()
    mount_plugin_systems(kernel=kernel, providers={EXTENSION_CATALOG: StubCatalog()})

    assert isinstance(resolve_system(EXTENSION_CATALOG, kernel=kernel), StubCatalog)
    assert isinstance(resolve_system(DESKTOP_PLUGIN_INSTALLER, kernel=kernel), DesktopPluginInstaller)


# ---------------------------------------------------------------------------
# swapping one live
# ---------------------------------------------------------------------------


def test_swapping_the_catalog_provider_changes_what_the_report_says() -> None:
    from thomas.server.plugin_kernel_mount import plugin_systems_report

    kernel = default_kernel()
    mounted = mount_plugin_systems(kernel=kernel)
    assert plugin_systems_report(kernel=kernel)["extension_packs"]["provider"] == "ExtensionCatalog"

    mounted.swap(EXTENSION_CATALOG, StubCatalog())

    report = plugin_systems_report(kernel=kernel)["extension_packs"]
    assert report["provider"] == "StubCatalog"
    assert report["count"] == 1
    assert report["mounted_on_kernel"] is True


def test_the_handle_follows_the_swap_so_the_next_one_works() -> None:
    """A stale fork in the handle would make the second swap fail as disposed."""
    kernel = default_kernel()
    mounted = mount_plugin_systems(kernel=kernel)

    mounted.swap(EXTENSION_CATALOG, StubCatalog())
    mounted.swap(EXTENSION_CATALOG, ExtensionCatalog())

    assert isinstance(resolve_system(EXTENSION_CATALOG, kernel=kernel), ExtensionCatalog)
    assert len([fork for fork in kernel.mounted() if fork.name == f"system:{EXTENSION_CATALOG}"]) == 1

    mounted.dispose()
    assert not kernel.root.has(EXTENSION_CATALOG)


# ---------------------------------------------------------------------------
# the consumer that makes it a seam
# ---------------------------------------------------------------------------


def test_the_desktop_facade_installs_through_the_mounted_service(process_kernel) -> None:
    """The path the marketplace import route already takes, redirected."""
    from thomas.server import desktop_plugins

    recorder = RecordingInstaller()
    mount_plugin_systems(kernel=process_kernel, providers={DESKTOP_PLUGIN_INSTALLER: recorder})

    result = desktop_plugins.install_plugin_bundle_bytes(
        {"config": "sentinel"},
        b"bundle-bytes",
        source={"type": "test"},
        require_signature=False,
    )

    assert result == {"ok": True, "installed_by": "recording"}
    assert recorder.calls[0]["bundle"] == b"bundle-bytes"
    assert recorder.calls[0]["require_signature"] is False


def _bundle(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def test_the_agent_installer_can_say_whether_a_bundle_is_its_own() -> None:
    """Called, not merely defined.

    ``accepts`` imported its detector from ``agent_plugins_adapter``, where that
    name has never lived — the adapter imports four *other* names from
    ``agent_plugins_manifest``. Every call raised ImportError, and nothing
    called it, so nothing said so. Exercising the provider's whole surface is
    what makes a default provider a working one rather than a plausible one.
    """
    installer = AgentPluginInstaller()
    plugin_json = json.dumps({"name": "demo-plugin", "version": "1.0.0"})

    assert installer.accepts(_bundle({"plugin.json": plugin_json})) is True
    # A bundle carrying a Thomas manifest belongs to the signed desktop path.
    assert installer.accepts(_bundle({"plugin.json": plugin_json, "manifest.json": "{}"})) is False
    assert installer.accepts(b"not a zip at all") is False


def test_the_agent_installer_hands_a_bundle_to_the_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    """``install`` is called here, and the name it reaches for has to exist.

    ``accepts`` was broken for exactly one reason: it imported a name from a
    module that does not export it, and no test ever called it. ``install``
    imports ``install_agent_plugin_bytes`` from ``agent_plugins_adapter`` the
    same deferred way, so this test calls it with the adapter replaced. The
    replacement is installed with ``monkeypatch.setattr``, which raises if the
    attribute is absent — so the import name is checked, not assumed, without
    unpacking a bundle onto the disk.
    """
    from thomas.server import agent_plugins_adapter

    seen: dict[str, Any] = {}

    def fake_install(config: Any, bundle_bytes: bytes, *, source: dict[str, Any]) -> dict[str, Any]:
        seen.update({"config": config, "bundle": bundle_bytes, "source": source})
        return {"ok": True, "installed": "demo-plugin"}

    monkeypatch.setattr(agent_plugins_adapter, "install_agent_plugin_bytes", fake_install)

    installer = AgentPluginInstaller()
    result = installer.install({"config": "sentinel"}, b"bundle-bytes", source={"type": "test"})

    assert result == {"ok": True, "installed": "demo-plugin"}
    assert seen == {"config": {"config": "sentinel"}, "bundle": b"bundle-bytes", "source": {"type": "test"}}


def test_every_default_provider_describes_itself() -> None:
    """``status()`` calls ``describe()`` on whatever is mounted."""
    kernel = default_kernel()
    mounted = mount_plugin_systems(kernel=kernel)

    rows = {row["service"]: row for row in mounted.status()}

    assert set(rows) == set(SYSTEM_SERVICES)
    for service in SYSTEM_SERVICES:
        assert rows[service]["mounted"] is True
        assert rows[service]["provider"]["kind"] in {"catalog", "installer"}


def test_the_report_states_which_systems_reached_the_kernel() -> None:
    from thomas.server.plugin_kernel_mount import plugin_systems_report

    kernel = default_kernel()
    before = plugin_systems_report(kernel=kernel)
    assert before["extension_packs"]["mounted_on_kernel"] is False
    assert before["agent_plugins"]["mounted_on_kernel"] is False

    mount_plugin_systems(kernel=kernel)
    after = plugin_systems_report(kernel=kernel)

    assert after["extension_packs"]["mounted_on_kernel"] is True
    assert after["agent_plugins"]["mounted_on_kernel"] is True
    assert after["desktop_plugins"]["mounted_on_kernel"] is True
    # Still true, and still measured rather than assumed: no pack code runs.
    assert after["extension_packs"]["hooks_execute"] is False
    assert kernel.root.has(AGENT_PLUGIN_INSTALLER)
