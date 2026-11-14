"""Phase 3.5: the live plugin controls, over HTTP.

`plans/thomas/tasks/PRAXIS-PHASE3-KERNEL/PLAN.md`.

These routes import Python from the plugins directory into the running process,
so the guard assertions here are not ceremony: every one of them, the read
included, must run ``require_api_access`` *and* ``require_loopback``. A reload
reachable from another machine is arbitrary code execution wearing a plugin
toggle's clothes.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from thomas.agent.kernel_wiring import default_kernel
from thomas.server.plugin_startup import APP_PLUGIN_SYSTEMS
from thomas.server.plugin_supervisor import PluginSupervisor
from thomas.server.plugin_systems_kernel import EXTENSION_CATALOG, mount_plugin_systems
from thomas.server.routes.plugin_kernel_routes import APP_PLUGINS_HANDLE, register_plugin_kernel_routes

_SOURCE = """
class Plugin:
    name = "route_demo"

    def before_tool(self, payload):
        data = dict(payload or {})
        data["mark"] = "{mark}"
        return data


def get_plugin():
    return Plugin()
"""


def _install(root: Path, mark: str) -> None:
    package = root / "route_demo"
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text(_SOURCE.replace("{mark}", mark), encoding="utf-8")
    manifest = {"plugins": {"route_demo": {"installed_path": str(package)}}}
    (root / "installed_plugins.json").write_text(json.dumps(manifest), encoding="utf-8")


class PluginKernelRouteTests(AioHTTPTestCase):
    """The supervised case: a plugin installed, mounted, and controllable."""

    supervised = True

    async def get_application(self) -> web.Application:
        self.guards: list[str] = []
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        previous = os.environ.get("THOMAS_PLUGIN_ENABLEMENT_STORE")
        os.environ["THOMAS_PLUGIN_ENABLEMENT_STORE"] = str(Path(tmp.name) / "enablement.json")

        def _restore_env() -> None:
            if previous is None:
                os.environ.pop("THOMAS_PLUGIN_ENABLEMENT_STORE", None)
            else:
                os.environ["THOMAS_PLUGIN_ENABLEMENT_STORE"] = previous

        self.addCleanup(_restore_env)

        self.root = Path(tmp.name) / "plugins"
        self.root.mkdir()
        _install(self.root, "v1")

        app = web.Application()
        if self.supervised:
            self.supervisor = PluginSupervisor(kernel=default_kernel(), install_root=str(self.root)).start()
            app[APP_PLUGINS_HANDLE] = self.supervisor
            self.addCleanup(self.supervisor.dispose)

        # The other three systems, mounted the way startup mounts them. Written
        # here rather than in a test body because the app is frozen once it
        # starts, and writing a key to a frozen app is deprecated.
        self.systems = mount_plugin_systems(kernel=default_kernel())
        app[APP_PLUGIN_SYSTEMS] = self.systems
        self.addCleanup(self.systems.dispose)

        register_plugin_kernel_routes(
            app,
            require_api_access=lambda request: self.guards.append("api"),
            require_loopback=lambda request: self.guards.append("loopback"),
            read_json=lambda request: request.json(),
        )
        return app

    async def test_status_reports_what_is_mounted(self) -> None:
        response = await self.client.get("/api/plugins/kernel")
        body = await response.json()

        self.assertEqual(response.status, 200)
        self.assertTrue(body["hot_swap"])
        self.assertEqual(body["handle"], "PluginSupervisor")
        self.assertEqual(body["runtime"]["mounted"], ["route_demo"])
        self.assertEqual(body["systems"]["installed_plugins"]["kind"], "runtime")

    async def test_every_route_runs_both_guards(self) -> None:
        self.guards.clear()
        await self.client.get("/api/plugins/kernel")
        await self.client.post("/api/plugins/kernel/unplug", json={"name": "route_demo"})
        await self.client.post("/api/plugins/kernel/replug", json={"name": "route_demo"})
        await self.client.post("/api/plugins/kernel/reload", json={"name": "route_demo"})
        await self.client.post("/api/plugins/kernel/sync", json={})

        self.assertEqual(self.guards, ["api", "loopback"] * 5)

    async def test_unplug_then_replug_over_http(self) -> None:
        unplugged = await (await self.client.post("/api/plugins/kernel/unplug", json={"name": "route_demo"})).json()
        self.assertTrue(unplugged["ok"])
        self.assertEqual(unplugged["mounted"], [])

        replugged = await (await self.client.post("/api/plugins/kernel/replug", json={"name": "route_demo"})).json()
        self.assertTrue(replugged["ok"])
        self.assertEqual(replugged["mounted"], ["route_demo"])

    async def test_reload_reports_the_outcome_word(self) -> None:
        unchanged = await (await self.client.post("/api/plugins/kernel/reload", json={"name": "route_demo"})).json()
        self.assertEqual(unchanged["outcome"], "unchanged")

        _install(self.root, "v2")
        reloaded = await (await self.client.post("/api/plugins/kernel/reload", json={"name": "route_demo"})).json()
        self.assertEqual(reloaded["outcome"], "reloaded")

    async def test_a_broken_edit_answers_200_with_ok_false(self) -> None:
        """The answer — your edit did not load — is the useful part of the reply."""
        (self.root / "route_demo" / "__init__.py").write_text("raise ValueError('nope')\n", encoding="utf-8")

        response = await self.client.post("/api/plugins/kernel/reload", json={"name": "route_demo"})
        body = await response.json()

        self.assertEqual(response.status, 200)
        self.assertFalse(body["ok"])
        self.assertEqual(body["outcome"], "failed")
        self.assertEqual(body["mounted"], ["route_demo"])

    async def test_a_request_without_a_name_is_refused(self) -> None:
        response = await self.client.post("/api/plugins/kernel/unplug", json={})
        self.assertEqual(response.status, 400)

    async def test_sync_reports_its_changes(self) -> None:
        _install(self.root, "v2")
        body = await (await self.client.post("/api/plugins/kernel/sync", json={})).json()

        self.assertTrue(body["ok"])
        self.assertEqual(body["changes"]["reloaded"], ["route_demo"])

    async def test_the_status_names_the_provider_answering_for_each_system(self) -> None:
        """Three systems, each with the provider currently mounted for it."""
        body = await (await self.client.get("/api/plugins/kernel")).json()

        rows = {row["service"]: row for row in body["system_services"]}
        self.assertEqual(
            sorted(rows),
            ["agent_plugin_installer", "desktop_plugin_installer", "extension_catalog"],
        )
        self.assertTrue(all(row["mounted"] for row in rows.values()))
        self.assertEqual(rows[EXTENSION_CATALOG]["provider"]["provider"], "ExtensionCatalog")

    async def test_a_system_provider_swapped_live_shows_up_in_the_status(self) -> None:
        """The swap is in-process; this is the surface that makes it observable."""

        class StubCatalog:
            name = "extensions"
            kind = "catalog"
            hooks_execute = False

            def packs(self, root=None):
                return []

            def describe(self):
                return {"provider": type(self).__name__, "name": self.name, "kind": self.kind}

        self.systems.swap(EXTENSION_CATALOG, StubCatalog())

        body = await (await self.client.get("/api/plugins/kernel")).json()

        rows = {row["service"]: row for row in body["system_services"]}
        self.assertEqual(rows[EXTENSION_CATALOG]["provider"]["provider"], "StubCatalog")
        self.assertTrue(rows[EXTENSION_CATALOG]["mounted"])


class UnsupervisedPluginKernelRouteTests(PluginKernelRouteTests):
    """A host that never started a supervisor says so instead of pretending."""

    supervised = False

    async def test_status_reports_what_is_mounted(self) -> None:
        body = await (await self.client.get("/api/plugins/kernel")).json()

        self.assertFalse(body["hot_swap"])
        self.assertEqual(body["handle"], "none")
        self.assertEqual(body["runtime"], {"supervised": False})

    async def test_every_route_runs_both_guards(self) -> None:
        self.guards.clear()
        await self.client.get("/api/plugins/kernel")
        await self.client.post("/api/plugins/kernel/sync", json={})

        self.assertEqual(self.guards, ["api", "loopback"] * 2)

    async def test_unplug_then_replug_over_http(self) -> None:
        response = await self.client.post("/api/plugins/kernel/unplug", json={"name": "route_demo"})
        self.assertEqual(response.status, 409)

    async def test_reload_reports_the_outcome_word(self) -> None:
        response = await self.client.post("/api/plugins/kernel/reload", json={"name": "route_demo"})
        self.assertEqual(response.status, 409)

    async def test_a_broken_edit_answers_200_with_ok_false(self) -> None:
        response = await self.client.post("/api/plugins/kernel/reload", json={"name": "route_demo"})
        self.assertEqual(response.status, 409)

    async def test_a_request_without_a_name_is_refused(self) -> None:
        response = await self.client.post("/api/plugins/kernel/unplug", json={})
        self.assertEqual(response.status, 409)

    async def test_sync_reports_its_changes(self) -> None:
        response = await self.client.post("/api/plugins/kernel/sync", json={})
        self.assertEqual(response.status, 409)
