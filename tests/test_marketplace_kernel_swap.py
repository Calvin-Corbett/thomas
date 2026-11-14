"""Phase 3.5: the marketplace routes read and install through kernel services.

`plans/thomas/tasks/PRAXIS-PHASE3-KERNEL/PLAN.md`.

The other kernel tests prove a swap on the plugin *status* surface. These prove
it on the surface the marketplace actually uses:

- ``GET /api/marketplace/plugins`` gets its catalog from the mounted
  ``extension_catalog`` provider, so a provider swapped in while the app is
  serving changes the next response — same running app, no restart.
- ``POST /api/marketplace/import`` asks the mounted ``agent_plugin_installer``
  provider whether it claims the bundle and hands it over if it does. Before
  phase 3.5 that route imported ``bundle_is_agent_plugin`` and
  ``install_agent_plugin_bytes`` directly and the service had no production
  caller at all.

Everything here mounts on the process-wide kernel (``mount_plugin_systems()``
with no argument), because that is the kernel the routes resolve against — the
same one ``thomas/server/plugin_startup.py`` mounts on at boot. Each test class
disposes what it mounted.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app_keys import APP_CONFIG
from thomas.server.plugin_systems_kernel import AGENT_PLUGIN_INSTALLER, EXTENSION_CATALOG, mount_plugin_systems
from thomas.server.routes.marketplace_catalog_aiohttp import register_marketplace_catalog_routes

DEMO_PLUGIN_ID = "kernel-swap-demo"


class DemoCatalog:
    """A catalog provider that serves one pack, named after the version it is on.

    Deliberately says nothing a reader would call placeholder wording: the
    surface policy hides rows whose text reads like vaporware, and a hidden row
    would make this test pass or fail for the wrong reason.
    """

    name = "extensions"
    kind = "catalog"
    hooks_execute = False

    def __init__(self, version: str, display_name: str) -> None:
        self.version = version
        self.display_name = display_name

    def load(self, root: Path | None = None) -> dict[str, Any]:
        return {
            "generated_at": "2026-09-25T00:00:00Z",
            "root": str(root or Path(tempfile.gettempdir())),
            "packs": [
                {
                    "id": DEMO_PLUGIN_ID,
                    "name": self.display_name,
                    "version": self.version,
                    "category": "demo",
                    "description": "served by whichever catalog provider is mounted right now",
                }
            ],
        }

    def packs(self, root: Path | None = None) -> list[Any]:
        return list(self.load(root=root)["packs"])

    def describe(self) -> dict[str, Any]:
        return {"provider": type(self).__name__, "name": self.name, "kind": self.kind}


class RecordingInstaller:
    """An agent-plugin installer provider that records instead of installing."""

    name = "agent-plugins"
    kind = "installer"

    def __init__(self, *, claims: bool) -> None:
        self.claims = claims
        self.asked: list[bytes] = []
        self.installed: list[tuple[Any, bytes, dict[str, Any]]] = []

    def accepts(self, bundle_bytes: bytes) -> bool:
        self.asked.append(bundle_bytes)
        return self.claims

    def install(self, config: Any, bundle_bytes: bytes, *, source: dict[str, Any]) -> dict[str, Any]:
        self.installed.append((config, bundle_bytes, source))
        return {"plugin_id": DEMO_PLUGIN_ID, "version": "9.9.9", "installed_by": type(self).__name__}

    def describe(self) -> dict[str, Any]:
        return {"provider": type(self).__name__, "name": self.name, "kind": self.kind}


class MarketplaceKernelSwapTests(AioHTTPTestCase):
    async def get_application(self) -> web.Application:
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.tmp_path = Path(tmp.name)
        self.config = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
            memory=MemoryConfig(root=tmp.name),
            server=ServerConfig(access_mode="local"),
        )

        # The process-wide kernel, mounted the way startup mounts it. The routes
        # resolve against this one, so nothing here is a special test kernel.
        self.systems = mount_plugin_systems()
        self.addCleanup(self.systems.dispose)

        app = web.Application()
        app[APP_CONFIG] = self.config
        register_marketplace_catalog_routes(app, require_api_access=lambda request: None)
        return app

    async def _catalog_rows(self) -> dict[str, dict[str, Any]]:
        response = await self.client.get("/api/marketplace/plugins?limit=50")
        self.assertEqual(response.status, 200)
        body = await response.json()
        self.assertIs(body.get("ok"), True)
        return {str(row.get("plugin_id")): row for row in (body.get("plugins") or [])}

    def _write_bundle(self, payload: bytes) -> Path:
        bundle = self.tmp_path / "bundle.zip"
        bundle.write_bytes(payload)
        return bundle

    async def test_the_default_providers_are_the_real_ones(self) -> None:
        """The swaps below start from what a real boot mounts, not from a fixture."""
        self.assertEqual(type(self.systems.provider(EXTENSION_CATALOG)).__name__, "ExtensionCatalog")
        self.assertEqual(type(self.systems.provider(AGENT_PLUGIN_INSTALLER)).__name__, "AgentPluginInstaller")

    async def test_the_catalog_route_answers_from_the_mounted_provider(self) -> None:
        self.systems.swap(EXTENSION_CATALOG, DemoCatalog("1.0.0", "Kernel Swap Demo"))

        rows = await self._catalog_rows()

        self.assertIn(DEMO_PLUGIN_ID, rows)
        self.assertEqual(rows[DEMO_PLUGIN_ID]["version"], "1.0.0")
        self.assertEqual(rows[DEMO_PLUGIN_ID]["display_name"], "Kernel Swap Demo")

    async def test_a_catalog_swapped_live_changes_the_next_response(self) -> None:
        """One running app, one client, two providers: the whole point of 3.5."""
        self.systems.swap(EXTENSION_CATALOG, DemoCatalog("1.0.0", "Kernel Swap Demo"))
        before = await self._catalog_rows()

        self.systems.swap(EXTENSION_CATALOG, DemoCatalog("2.0.0", "Kernel Swap Demo Two"))
        after = await self._catalog_rows()

        self.assertEqual(before[DEMO_PLUGIN_ID]["version"], "1.0.0")
        self.assertEqual(before[DEMO_PLUGIN_ID]["display_name"], "Kernel Swap Demo")
        self.assertEqual(after[DEMO_PLUGIN_ID]["version"], "2.0.0")
        self.assertEqual(after[DEMO_PLUGIN_ID]["display_name"], "Kernel Swap Demo Two")

    async def test_the_import_route_installs_through_the_agent_installer_provider(self) -> None:
        installer = RecordingInstaller(claims=True)
        self.systems.swap(AGENT_PLUGIN_INSTALLER, installer)
        bundle = self._write_bundle(b"an agent plugin bundle, as far as this provider is concerned")

        response = await self.client.post("/api/marketplace/import", json={"path": str(bundle)})
        body = await response.json()

        self.assertEqual(response.status, 200)
        self.assertIs(body.get("ok"), True)
        self.assertEqual(body["plugin"]["installed_by"], "RecordingInstaller")
        self.assertEqual(installer.asked, [bundle.read_bytes()])
        recorded_config, recorded_bytes, recorded_source = installer.installed[0]
        self.assertIs(recorded_config, self.config)
        self.assertEqual(recorded_bytes, bundle.read_bytes())
        # The route resolves the request-controlled path before reading it — that
        # is its traversal guard — so the provider is handed the resolved path.
        # On Windows the temp dir can arrive as an 8.3 short name
        # (``C:\Users\THOMAS~1\...``), which resolves to its long form, so
        # compare against the resolved path rather than the string we posted.
        self.assertEqual(recorded_source, {"type": "file_import", "path": str(bundle.resolve())})

    async def test_a_provider_that_refuses_the_bundle_leaves_the_signed_path_alone(self) -> None:
        """Refusing is half the contract: the desktop installer still gets it."""
        installer = RecordingInstaller(claims=False)
        self.systems.swap(AGENT_PLUGIN_INSTALLER, installer)
        bundle = self._write_bundle(b"not a zip, so the signed path will reject it")

        response = await self.client.post("/api/marketplace/import", json={"path": str(bundle)})
        body = await response.json()

        self.assertEqual(installer.asked, [bundle.read_bytes()])
        self.assertEqual(installer.installed, [])
        self.assertIs(body.get("ok"), False)
