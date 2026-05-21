from __future__ import annotations

import hashlib
import io
import json
import tempfile
import threading
import unittest
import zipfile
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import httpx
from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app
from thomas.server.desktop_plugins import build_plugin_install_deep_link

ROOT = Path(__file__).resolve().parent.parent


def _read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _exists(relative_path: str) -> bool:
    return (ROOT / relative_path).exists()


def _read_all_runtime_js() -> str:
    """Read and concatenate all split runtime JS files in order."""
    runtime_dir = ROOT / "thomas" / "server" / "web" / "js" / "runtime"
    if not runtime_dir.exists():
        return ""
    parts = sorted(runtime_dir.glob("*.js"))
    return "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in parts)


@contextmanager
def _hosted_plugin_store(bundle_paths: dict[str, Path]):
    bundles: dict[str, tuple[bytes, str]] = {}
    for plugin_id, path in bundle_paths.items():
        payload = path.read_bytes()
        bundles[plugin_id] = (payload, hashlib.sha256(payload).hexdigest())

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return

        def _write_json(self, payload: dict, *, status: int = 200) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or "0")
            raw_body = self.rfile.read(length) if length > 0 else b""
            try:
                body = json.loads(raw_body.decode("utf-8")) if raw_body else {}
            except json.JSONDecodeError:
                body = {}

            plugin_id = str(body.get("plugin_id") or "")
            if self.path == "/api/v1/plugins/download-token":
                if self.headers.get("X-Thomas-API-Key") != "local-dev-install-key":
                    self._write_json({"error": "Missing or invalid API key"}, status=401)
                    return
                bundle = bundles.get(plugin_id)
                if bundle is None:
                    self._write_json({"error": "Plugin not found"}, status=404)
                    return
                bundle_bytes, bundle_sha256 = bundle
                self._write_json(
                    {
                        "plugin_id": plugin_id,
                        "download_url": f"/api/v1/plugins/download/{plugin_id}-token",
                        "sha256": bundle_sha256,
                        "size_bytes": len(bundle_bytes),
                    }
                )
                return

            if self.path == "/api/v1/plugins/verify":
                bundle = bundles.get(plugin_id)
                if bundle is None:
                    self._write_json({"valid": False, "error": "Plugin not found"}, status=404)
                    return
                bundle_bytes, bundle_sha256 = bundle
                self._write_json({"valid": True, "sha256": bundle_sha256, "size_bytes": len(bundle_bytes)})
                return

            self._write_json({"error": "Not found"}, status=404)

        def do_GET(self):
            if not self.path.startswith("/api/v1/plugins/download/"):
                self._write_json({"error": "Not found"}, status=404)
                return
            token = self.path.rsplit("/", 1)[-1]
            plugin_id = token.removesuffix("-token")
            bundle = bundles.get(plugin_id)
            if bundle is None:
                self._write_json({"error": "Not found"}, status=404)
                return
            bundle_bytes, bundle_sha256 = bundle
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(len(bundle_bytes)))
            self.send_header("X-Plugin-SHA256", bundle_sha256)
            self.end_headers()
            self.wfile.write(bundle_bytes)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@contextmanager
def _hosted_marketplace_catalog(payload: dict[str, object]):
    body = json.dumps(payload).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return

        def do_GET(self):
            if not self.path.startswith("/api/marketplace/catalog"):
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


class TestServerMarketplaceRoutes(AioHTTPTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)

    def tearDown(self) -> None:
        try:
            self._tmpdir.cleanup()
        finally:
            super().tearDown()

    async def get_application(self):
        cfg = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
            memory=MemoryConfig(root=self._tmpdir.name),
            server=ServerConfig(access_mode="local"),
        )
        return create_app(cfg)

    async def _materialize_hosted_bundles(self, plugin_ids: list[str]) -> dict[str, Path]:
        """
        Download each plugin bundle via the marketplace download route and
        write the bytes into ``self._tmpdir``. Returns a {plugin_id: path}
        map suitable for :func:`_hosted_plugin_store`.

        Registry directories like ``thomas/server/plugins_registry/plugins/
        life-manager/`` ship only ``manifest.json`` — bundles are generated
        at runtime, so we can't rely on a pre-existing ``bundle.zip`` file.
        """
        out: dict[str, Path] = {}
        for plugin_id in plugin_ids:
            download_resp = await self.client.get(f"/api/marketplace/plugins/{plugin_id}/download")
            self.assertEqual(download_resp.status, 200, f"download failed for {plugin_id}")
            bundle_bytes = await download_resp.read()
            bundle_path = Path(self._tmpdir.name) / f"{plugin_id}.bundle.zip"
            bundle_path.write_bytes(bundle_bytes)
            out[plugin_id] = bundle_path
        return out

    async def test_marketplace_plugin_catalog_route_returns_real_extension_packs(self):
        resp = await self.client.get("/api/marketplace/plugins?limit=25")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertIs(body.get("ok"), True)
        self.assertGreaterEqual(int(body.get("total") or 0), 480)
        self.assertEqual(body.get("offset"), 0)
        self.assertEqual(body.get("limit"), 25)
        self.assertIsInstance(body.get("types"), list)
        plugins = body.get("plugins") or []
        self.assertEqual(len(plugins), 25)
        first = plugins[0] or {}
        self.assertTrue(str(first.get("id") or "").strip())
        self.assertTrue(str(first.get("name") or "").strip())
        self.assertTrue(str(first.get("category") or "").strip())
        self.assertIsInstance(first.get("capabilities"), list)
        self.assertIsInstance(first.get("categories"), list)
        self.assertIsInstance(first.get("tags"), list)
        self.assertTrue(str(first.get("marketplace_type") or "").strip())
        self.assertTrue(str(first.get("download_url") or "").endswith("/download"))
        self.assertIsInstance(first.get("download_available"), bool)
        self.assertTrue(str(first.get("download_filename") or "").endswith(".zip"))

    async def test_marketplace_plugin_catalog_route_filters_by_query_category_and_type(self):
        resp = await self.client.get(
            "/api/marketplace/plugins?category=productivity&type=dependency&q=foundation&limit=20"
        )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        plugins = body.get("plugins") or []
        self.assertEqual(len(plugins), 1)
        plugin = plugins[0]
        self.assertEqual(str(plugin.get("id") or ""), "life-manager-foundation")
        self.assertEqual(str(plugin.get("category") or ""), "productivity")
        self.assertEqual(str(plugin.get("marketplace_type") or ""), "dependency")
        self.assertEqual(str(plugin.get("left_nav_behavior") or ""), "none")

    async def test_marketplace_catalog_exposes_life_manager_as_command_center(self):
        resp = await self.client.get("/api/marketplace/plugins?category=productivity&limit=20")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        plugins = {str(row.get("id")): row for row in (body.get("plugins") or [])}
        life_manager = plugins.get("life-manager") or {}
        dependency = plugins.get("life-manager-foundation") or {}
        self.assertEqual(life_manager.get("marketplace_type"), "command_center")
        self.assertEqual(life_manager.get("left_nav_behavior"), "workspace")
        self.assertEqual(life_manager.get("requires"), ["life-manager-foundation"])
        self.assertEqual(dependency.get("marketplace_type"), "dependency")
        self.assertEqual(dependency.get("left_nav_behavior"), "none")

    async def test_marketplace_plugin_download_route_streams_real_extension_pack(self):
        catalog_resp = await self.client.get("/api/marketplace/plugins?category=alerts&q=slack&limit=20")
        self.assertEqual(catalog_resp.status, 200)
        catalog_body = await catalog_resp.json()
        plugin = next((row for row in (catalog_body.get("plugins") or []) if row.get("download_available")), None)
        self.assertIsNotNone(plugin)

        plugin_id = str(plugin.get("id") or "")
        download_url = str(plugin.get("download_url") or "")
        download_filename = str(plugin.get("download_filename") or "")

        resp = await self.client.get(download_url)
        self.assertEqual(resp.status, 200)
        self.assertIn("application/zip", resp.headers.get("Content-Type", ""))
        self.assertIn(download_filename, resp.headers.get("Content-Disposition", ""))

        payload = await resp.read()
        self.assertGreater(len(payload), 0)

        with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
            names = archive.namelist()
            self.assertIn(f"{plugin_id}/manifest.json", names)
            self.assertIn(f"{plugin_id}/hooks.py", names)
            self.assertIn(f"{plugin_id}/README.md", names)
            self.assertTrue(all("__pycache__" not in name for name in names))
            manifest = json.loads(archive.read(f"{plugin_id}/manifest.json").decode("utf-8"))

        self.assertEqual(manifest.get("id"), plugin_id)

    async def test_marketplace_plugin_download_route_returns_404_for_unknown_pack(self):
        resp = await self.client.get("/api/marketplace/plugins/not-a-real-pack/download")
        self.assertEqual(resp.status, 404)
        body = await resp.json()
        self.assertIs(body.get("ok"), False)
        self.assertIn("not found", str(body.get("error") or "").lower())

    async def test_marketplace_install_lists_and_serves_life_manager_plugin(self):
        install_resp = await self.client.post("/api/marketplace/plugins/life-manager/install")
        self.assertEqual(install_resp.status, 200)
        install_body = await install_resp.json()
        plugin = install_body.get("plugin") or {}
        self.assertEqual(plugin.get("plugin_id"), "life-manager")
        self.assertEqual(plugin.get("mode_id"), "life_manager")
        self.assertEqual(plugin.get("marketplace_type"), "command_center")
        self.assertEqual(plugin.get("left_nav_behavior"), "workspace")
        self.assertEqual(plugin.get("surface_mode"), "immersive")
        surface_url = str(plugin.get("surface_url") or "")
        self.assertTrue(surface_url.endswith("/plugins/life-manager/web/index.html"))

        listed_resp = await self.client.get("/api/marketplace/installed")
        self.assertEqual(listed_resp.status, 200)
        listed_body = await listed_resp.json()
        installed = listed_body.get("plugins") or []
        installed_ids = {row.get("plugin_id"): row for row in installed}
        self.assertEqual(set(installed_ids), {"life-manager", "life-manager-foundation"})
        self.assertEqual(installed_ids["life-manager-foundation"].get("marketplace_type"), "dependency")
        self.assertEqual(installed_ids["life-manager-foundation"].get("left_nav_behavior"), "none")
        self.assertEqual(installed_ids["life-manager"].get("workspace_id"), "life_manager")

        surface_resp = await self.client.get(surface_url)
        self.assertEqual(surface_resp.status, 200)
        self.assertIn("text/html", surface_resp.headers.get("Content-Type", ""))
        surface_html = await surface_resp.text()
        self.assertIn("Life Manager", surface_html)

    async def test_index_route_injects_runtime_build_fingerprint(self):
        resp = await self.client.get("/")
        self.assertEqual(resp.status, 200)
        body = await resp.text()
        self.assertIn("/static/js/app.js?v=", body)
        self.assertNotIn("__THOMAS_WEB_BUILD__", body)
        self.assertNotIn("app.js?v=__THOMAS_VERSION__", body)

    async def test_marketplace_import_from_file_installs_signed_bundle_and_dependency(self):
        download_resp = await self.client.get("/api/marketplace/plugins/life-manager/download")
        self.assertEqual(download_resp.status, 200)
        bundle_path = Path(self._tmpdir.name) / "life-manager.zip"
        bundle_path.write_bytes(await download_resp.read())

        import_resp = await self.client.post("/api/marketplace/import", json={"path": str(bundle_path)})
        self.assertEqual(import_resp.status, 200)
        import_body = await import_resp.json()
        plugin = import_body.get("plugin") or {}
        self.assertEqual(plugin.get("plugin_id"), "life-manager")
        self.assertEqual(plugin.get("publisher_id"), "thomas-official")

        listed_resp = await self.client.get("/api/marketplace/installed")
        installed = (await listed_resp.json()).get("plugins") or []
        self.assertEqual({row.get("plugin_id") for row in installed}, {"life-manager", "life-manager-foundation"})

    async def test_marketplace_installs_hosted_plugin_from_deep_link_without_duplicates(self):
        bundle_paths = await self._materialize_hosted_bundles(["life-manager", "life-manager-foundation"])
        with _hosted_plugin_store(bundle_paths) as store:
            deep_link = build_plugin_install_deep_link("life-manager", store, channel="stable")

            install_resp = await self.client.post(
                "/api/marketplace/install-from-deep-link", json={"deep_link": deep_link}
            )
            self.assertEqual(install_resp.status, 200)
            install_body = await install_resp.json()
            plugin = install_body.get("plugin") or {}
            request = install_body.get("request") or {}
            self.assertEqual(request.get("plugin_id"), "life-manager")
            self.assertEqual(request.get("store"), store)
            self.assertEqual(plugin.get("plugin_id"), "life-manager")
            self.assertEqual((plugin.get("source") or {}).get("type"), "hosted")

            second_resp = await self.client.post(
                "/api/marketplace/install-from-deep-link", json={"deep_link": deep_link}
            )
            self.assertEqual(second_resp.status, 200)

            listed_resp = await self.client.get("/api/marketplace/installed")
            self.assertEqual(listed_resp.status, 200)
            listed_body = await listed_resp.json()
            installed = listed_body.get("plugins") or []
            self.assertEqual({row.get("plugin_id") for row in installed}, {"life-manager", "life-manager-foundation"})

    async def test_marketplace_install_accepts_store_url_payload_for_hosted_plugins(self):
        bundle_paths = await self._materialize_hosted_bundles(["life-manager", "life-manager-foundation"])
        with _hosted_plugin_store(bundle_paths) as store:
            install_resp = await self.client.post(
                "/api/marketplace/plugins/life-manager/install",
                json={"store_url": store, "channel": "stable"},
            )
            self.assertEqual(install_resp.status, 200)
            install_body = await install_resp.json()
            plugin = install_body.get("plugin") or {}
            self.assertEqual(plugin.get("plugin_id"), "life-manager")
            self.assertEqual((plugin.get("source") or {}).get("type"), "hosted")
            self.assertEqual((plugin.get("source") or {}).get("store_url"), store)

    async def test_marketplace_sync_reads_hosted_catalog_and_marks_available_updates(self):
        install_resp = await self.client.post("/api/marketplace/plugins/life-manager/install")
        self.assertEqual(install_resp.status, 200)

        payload = {
            "ok": True,
            "generated_at": "2026-03-27T15:00:00Z",
            "store_url": "https://thomas.dev",
            "channel": "stable",
            "plugins": [
                {
                    "id": "life-manager",
                    "plugin_id": "life-manager",
                    "name": "Life Manager",
                    "display_name": "Life Manager",
                    "version": "2.0.0",
                    "subtitle": "Hosted workspace plugin",
                    "description": "Hosted catalog row",
                    "category": "productivity",
                    "category_label": "Productivity",
                    "categories": ["productivity", "automation"],
                    "tags": ["official", "command_center"],
                    "requires": ["life-manager-foundation"],
                    "target": "desktop",
                    "mode": "life_manager",
                    "mode_id": "life_manager",
                    "marketplace_type": "command_center",
                    "marketplace_type_label": "Command Center",
                    "left_nav_behavior": "workspace",
                    "default_nav_section": "command_centers",
                    "default_nav_order": 520,
                    "entrypoint": "hooks.py",
                    "capabilities": ["life_manager.tasks"],
                    "kind": "desktop_plugin",
                    "source": "website/hosted-plugin-store",
                    "publisher_id": "thomas-official",
                    "publisher_name": "Thomas",
                    "icon": "ph-list-checks",
                    "api_namespace": "life-manager",
                    "download_available": True,
                    "installable": True,
                    "installed": False,
                    "enabled": False,
                    "workspace_id": "life_manager",
                    "download_url": "https://thomas.dev/api/v1/plugins/life-manager/manual-download",
                    "manual_download_url": "https://thomas.dev/api/v1/plugins/life-manager/manual-download",
                    "detail_url": "https://thomas.dev/api/v1/plugins/life-manager",
                    "open_in_thomas_url": "thomas://install-plugin?plugin_id=life-manager&store=https%3A%2F%2Fthomas.dev&channel=stable",
                    "store_url": "https://thomas.dev",
                    "channel": "stable",
                    "surface": {"entry_html": "web/index.html", "title": "Life Manager", "surface_mode": "immersive"},
                }
            ],
        }
        with (
            _hosted_marketplace_catalog(payload) as store,
            patch.dict("os.environ", {"THOMAS_MARKETPLACE_STORE_URL": store}),
        ):
            sync_resp = await self.client.get("/api/marketplace/sync?limit=25")

        self.assertEqual(sync_resp.status, 200)
        sync_body = await sync_resp.json()
        self.assertIs(sync_body.get("ok"), True)
        self.assertEqual(sync_body.get("sync_source"), "hosted_catalog")
        self.assertEqual(sync_body.get("source_label"), store.replace("http://", ""))
        self.assertEqual(sync_body.get("store_url"), store)
        self.assertEqual(sync_body.get("update_candidates"), ["life-manager"])
        plugins = {str(row.get("plugin_id")): row for row in (sync_body.get("plugins") or [])}
        installed_rows = {str(row.get("plugin_id")): row for row in (sync_body.get("installed") or [])}
        self.assertTrue(plugins["life-manager"].get("installed"))
        self.assertTrue(plugins["life-manager"].get("enabled"))
        self.assertTrue(plugins["life-manager"].get("update_available"))
        self.assertEqual(plugins["life-manager"].get("installed_version"), "1.0.0")
        self.assertEqual(installed_rows["life-manager"].get("left_nav_behavior"), "workspace")
        self.assertEqual(installed_rows["life-manager"].get("workspace_id"), "life_manager")

    async def test_marketplace_sync_falls_back_to_local_catalog_on_dns_failure(self):
        with patch(
            "thomas.server.routes.marketplace_catalog_aiohttp._load_hosted_marketplace_catalog",
            side_effect=httpx.ConnectError("[Errno 11001] getaddrinfo failed"),
        ):
            sync_resp = await self.client.get("/api/marketplace/sync?limit=25")

        self.assertEqual(sync_resp.status, 200)
        sync_body = await sync_resp.json()
        self.assertIs(sync_body.get("ok"), True)
        self.assertEqual(sync_body.get("sync_source"), "local_catalog_fallback")
        self.assertIs(sync_body.get("degraded"), True)
        self.assertIn("Unable to sync marketplace catalog from", str(sync_body.get("sync_error") or ""))
        self.assertGreater(int(sync_body.get("total") or 0), 0)
        self.assertIn("https://thomas-site.thomasdevhub.workers.dev", sync_body.get("attempted_store_urls") or [])

    async def test_marketplace_sync_automatically_falls_through_to_live_worker_host(self):
        payload = {
            "ok": True,
            "generated_at": "2026-03-27T15:00:00Z",
            "store_url": "https://thomas-site.thomasdevhub.workers.dev",
            "channel": "stable",
            "plugins": [],
        }

        async def fake_load_hosted_marketplace_catalog(*, store_url: str, channel: str):
            if store_url == "https://thomas.dev":
                raise httpx.ConnectError("[Errno 11001] getaddrinfo failed")
            if store_url == "https://thomas-site.thomasdevhub.workers.dev":
                return payload
            raise AssertionError(f"Unexpected store URL {store_url!r}")

        with (
            patch.dict("os.environ", {"SITE_URL": "https://thomas.dev"}, clear=False),
            patch(
                "thomas.server.routes.marketplace_catalog_aiohttp._load_hosted_marketplace_catalog",
                side_effect=fake_load_hosted_marketplace_catalog,
            ),
        ):
            sync_resp = await self.client.get("/api/marketplace/sync?limit=25")

        self.assertEqual(sync_resp.status, 200)
        sync_body = await sync_resp.json()
        self.assertIs(sync_body.get("ok"), True)
        self.assertEqual(sync_body.get("sync_source"), "hosted_catalog")
        self.assertEqual(sync_body.get("store_url"), "https://thomas-site.thomasdevhub.workers.dev")
        self.assertEqual(
            sync_body.get("attempted_store_urls"),
            ["https://thomas.dev", "https://thomas-site.thomasdevhub.workers.dev"],
        )

    async def test_marketplace_rejects_invalid_deep_link_install_requests(self):
        install_resp = await self.client.post(
            "/api/marketplace/install-from-deep-link", json={"deep_link": "https://example.com/plugin"}
        )
        self.assertEqual(install_resp.status, 400)
        install_body = await install_resp.json()
        self.assertIn("thomas://", str(install_body.get("error") or "").lower())

    async def test_marketplace_enable_disable_and_uninstall_control_life_manager_access(self):
        install_resp = await self.client.post("/api/marketplace/plugins/life-manager/install")
        self.assertEqual(install_resp.status, 200)
        plugin = (await install_resp.json()).get("plugin") or {}
        surface_url = str(plugin.get("surface_url") or "")

        bootstrap_resp = await self.client.get("/api/plugins/life-manager/bootstrap")
        self.assertEqual(bootstrap_resp.status, 200)
        bootstrap_body = await bootstrap_resp.json()
        self.assertEqual(bootstrap_body.get("state", {}).get("tasks"), [])

        disable_resp = await self.client.post("/api/marketplace/plugins/life-manager/disable")
        self.assertEqual(disable_resp.status, 200)
        disabled_plugin = (await disable_resp.json()).get("plugin") or {}
        self.assertIs(disabled_plugin.get("enabled"), False)

        disabled_bootstrap = await self.client.get("/api/plugins/life-manager/bootstrap")
        self.assertEqual(disabled_bootstrap.status, 404)
        disabled_surface = await self.client.get(surface_url)
        self.assertEqual(disabled_surface.status, 403)

        enable_resp = await self.client.post("/api/marketplace/plugins/life-manager/enable")
        self.assertEqual(enable_resp.status, 200)
        enabled_plugin = (await enable_resp.json()).get("plugin") or {}
        self.assertIs(enabled_plugin.get("enabled"), True)

        uninstall_resp = await self.client.post("/api/marketplace/plugins/life-manager/uninstall")
        self.assertEqual(uninstall_resp.status, 200)
        uninstall_body = await uninstall_resp.json()
        self.assertIs(uninstall_body.get("removed"), True)

        listed_resp = await self.client.get("/api/marketplace/installed")
        listed_body = await listed_resp.json()
        installed = listed_body.get("plugins") or []
        self.assertEqual(installed, [])

        removed_bootstrap = await self.client.get("/api/plugins/life-manager/bootstrap")
        self.assertEqual(removed_bootstrap.status, 404)

    async def test_marketplace_rejects_unsafe_plugin_asset_paths(self):
        install_resp = await self.client.post("/api/marketplace/plugins/life-manager/install")
        self.assertEqual(install_resp.status, 200)
        unsafe_resp = await self.client.get("/plugins/life-manager/..%2Fmanifest.json")
        self.assertEqual(unsafe_resp.status, 404)

    async def test_life_manager_bootstrap_and_crud_roundtrip(self):
        install_resp = await self.client.post("/api/marketplace/plugins/life-manager/install")
        self.assertEqual(install_resp.status, 200)

        create_task = await self.client.post(
            "/api/plugins/life-manager/tasks",
            json={"title": "Pay rent", "priority": "high", "target_date": "2026-03-17"},
        )
        self.assertEqual(create_task.status, 201)
        task = (await create_task.json()).get("item") or {}
        task_id = str(task.get("id") or "")
        self.assertTrue(task_id.startswith("task-"))

        update_task = await self.client.patch(
            f"/api/plugins/life-manager/tasks/{task_id}",
            json={"status": "done"},
        )
        self.assertEqual(update_task.status, 200)
        updated_task = (await update_task.json()).get("item") or {}
        self.assertEqual(updated_task.get("status"), "done")

        create_agenda = await self.client.post(
            "/api/plugins/life-manager/agenda",
            json={"title": "Doctor visit", "date": "2026-03-17", "start_time": "09:00", "end_time": "10:00"},
        )
        self.assertEqual(create_agenda.status, 201)

        create_habit = await self.client.post(
            "/api/plugins/life-manager/habits",
            json={"title": "Drink water", "cadence": "daily", "target_count": 8},
        )
        self.assertEqual(create_habit.status, 201)

        create_goal = await self.client.post(
            "/api/plugins/life-manager/goals",
            json={"title": "Ship plugin system", "horizon": "quarter", "progress": 40},
        )
        self.assertEqual(create_goal.status, 201)

        bootstrap_resp = await self.client.get("/api/plugins/life-manager/bootstrap")
        self.assertEqual(bootstrap_resp.status, 200)
        state = (await bootstrap_resp.json()).get("state") or {}
        self.assertEqual(len(state.get("tasks") or []), 1)
        self.assertEqual(len(state.get("agenda") or []), 1)
        self.assertEqual(len(state.get("habits") or []), 1)
        self.assertEqual(len(state.get("goals") or []), 1)
        self.assertEqual((state.get("tasks") or [])[0].get("status"), "done")

        delete_task = await self.client.delete(f"/api/plugins/life-manager/tasks/{task_id}")
        self.assertEqual(delete_task.status, 200)
        final_bootstrap = await self.client.get("/api/plugins/life-manager/bootstrap")
        final_state = (await final_bootstrap.json()).get("state") or {}
        self.assertEqual(final_state.get("tasks"), [])


def test_marketplace_surface_uses_plugin_catalog_only() -> None:
    html = _read_text("thomas/server/web/static/plugin_marketplace.html")
    script = _read_text("thomas/server/web/static/plugin_marketplace.script01.js")

    assert "/api/marketplace/plugins" in script
    assert "/api/companion/v1/app-store" not in script
    assert "/api/companion/v1/modules" not in script
    assert "Thomas Companion" not in html
    assert "extensions/catalog.json" in html
    assert "Loading Thomas upgrades..." in script
    assert "No upgrades match this view." in script
    assert "No upgrade metadata yet." in script
    assert "ReactDOM" not in html
    assert "react-dom" not in html.lower()
    assert "unpkg.com/react" not in html
    assert "babel" not in html.lower()


def test_marketplace_runtime_supports_reorderable_workspace_nav_and_import() -> None:
    script = _read_all_runtime_js()

    assert "/api/marketplace/sync" in script
    assert "/api/marketplace/import" in script
    assert "/api/marketplace/install-from-deep-link" in script
    assert "workspaceNavItems" in script
    assert "UI_WORKSPACE_NAV_ORDER_STORAGE_KEY" in script
    assert "dragstart" in script
    assert "marketplace_type" in script
    assert "requires" in script
    assert "Install From File" in script
    assert "actionId === 'open'" in script
    assert "label: 'Open'" in script
    assert "UI_MARKETPLACE_STORE_URL_STORAGE_KEY" in script
    assert "DEFAULT_MARKETPLACE_STORE_URL" in script
    assert "Marketplace Source" not in script
    assert "thomas_deep_link" in script
    assert "Synced from" in script
    assert "__THOMAS_WEB_BUILD__" in _read_text("thomas/server/web/index.html")


def test_workspace_nav_clicks_are_wired_to_open_dynamic_workspaces() -> None:
    script = _read_all_runtime_js()

    assert "if (workspaceNavItems)" in script
    assert "workspaceNavItems.addEventListener('click'" in script
    assert "setSidebarNavMode(mode);" in script


def test_workspaces_render_in_sidebar_markup() -> None:
    html = _read_text("thomas/server/web/index.html")

    assert "Workspaces" in html
    assert html.index("Workspaces") < html.index("workspaceNavItems")
    assert "pluginNavItems" in html


def test_marketplace_runtime_uses_store_specific_empty_state_copy() -> None:
    script = _read_all_runtime_js()
    static_html = _read_text("thomas/server/web/static/plugin_marketplace.html")
    static_script = _read_text("thomas/server/web/static/plugin_marketplace.script01.js")

    assert "Browse and install Thomas upgrades" in script
    assert "Browse and install Thomas upgrades from the marketplace catalog." in script
    assert "Marketplace catalog" in script
    assert "Marketplace is syncing upgrades." in script
    assert "Loading upgrades..." in script
    assert "No upgrades match this view." in script
    assert "All Upgrades" in script
    assert "Installable Thomas plugins from the extension catalog." not in script
    assert "No live queue data yet." not in script
    assert "moduleWorkspaceMeta.textContent = 'Extension catalog';" not in script
    assert "Browse real Thomas upgrades from the marketplace catalog." in static_html
    assert "Browse real Thomas plugins from the extension catalog." not in static_html
    assert "Source: marketplace catalog" in static_script
    assert "extension catalog" not in static_script.lower()


def test_tray_agent_bootstraps_repo_runtime_and_prefers_repo_venv() -> None:
    tray_main = _read_text("thomas/tray_agent/__main__.py")
    tray_agent = _read_text("thomas/tray_agent/agent.py")

    assert "pyproject.toml" in tray_main
    assert "sys.path.insert(0, repo_root)" in tray_main
    assert ".venv" in tray_agent
    assert "_get_repo_root()" in tray_agent
    assert "cwd = str(_get_repo_root())" in tray_agent


def test_windows_launcher_registers_protocol_and_forwards_deep_links() -> None:
    script = _read_text("scripts/run-ui.ps1")

    assert "URL Protocol" in script
    assert "thomas_deep_link" in script
    assert "__THOMAS_WEB_BUILD__" in _read_text("thomas/server/web/index.html")
    assert '-DeepLink "%1"' in script
    assert "Get-ThomasLaunchUrl" in script
    assert "[switch]$Tray" in script
    assert "$PSBoundParameters.ContainsKey('NoTray')" in script
    assert "[switch]$Tray" in script
    assert "$PSBoundParameters.ContainsKey('NoTray')" in script
    assert "[switch]$Tray" in script
    assert "$PSBoundParameters.ContainsKey('NoTray')" in script


def test_marketplace_has_single_backend_source_of_truth() -> None:
    app_part03 = _read_text("thomas/server/app_part03.py")

    assert "register_marketplace_routes" not in app_part03
    assert "routes.marketplace import" not in app_part03
    assert "register_marketplace_catalog_routes" in app_part03
    assert "register_plugin_hosting_routes" in app_part03
    assert "register_life_manager_routes" in app_part03
    assert _exists("thomas/server/routes/marketplace_catalog_aiohttp.py")


def test_public_site_marketplace_routes_and_page_exist() -> None:
    site_config = _read_text("apps/site/src/lib/site-config.ts")
    # The marketplace route file (`page.tsx`) is now a thin server-component
    # wrapper that delegates to `SiteMarketplacePage`. The canonical marker
    # strings (`Website-canonical Thomas Marketplace`, `catalog_only`) live
    # in the imported client component. Read both files so the contract
    # check covers the route file PLUS its rendered content — and so the
    # test does not require touching `page.tsx` (which would force a fresh
    # site visual-proof refresh on every commit).
    marketplace_page = _read_text("apps/site/src/app/marketplace/page.tsx")
    marketplace_component = _read_text("apps/site/src/components/site-marketplace-page.tsx")
    marketplace_surface = marketplace_page + "\n" + marketplace_component
    catalog_route = _read_text("apps/site/src/app/api/marketplace/catalog/route.ts")
    versioned_catalog_route = _read_text("apps/site/src/app/api/v1/plugins/catalog/route.ts")
    download_token_route = _read_text("apps/site/src/app/api/v1/plugins/download-token/route.ts")
    detail_route = _read_text("apps/site/src/app/api/v1/plugins/[pluginId]/route.ts")

    assert 'href: "/marketplace"' in site_config
    assert "SiteMarketplacePage" in marketplace_page
    assert "Website-canonical Thomas Marketplace" in marketplace_surface
    assert "catalog_only" in marketplace_surface
    assert "buildMarketplaceCatalog" in catalog_route
    assert "buildMarketplaceCatalog" in versioned_catalog_route
    assert "getMarketplaceInstallablePlugin" in detail_route
    assert "X-Thomas-API-Key" in download_token_route


if __name__ == "__main__":
    unittest.main()
