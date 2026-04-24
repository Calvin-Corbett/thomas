from __future__ import annotations

import json
import tempfile
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app
from thomas.server.routes import marketplace_catalog_aiohttp as marketplace_routes


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


class TestMarketplaceRoutePolicy(AioHTTPTestCase):
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

    async def test_marketplace_sync_without_store_uses_local_catalog(self):
        response = await self.client.get("/api/marketplace/sync")
        self.assertEqual(response.status, 200)
        body = await response.json()

        self.assertEqual(body.get("sync_source"), "local_catalog")
        self.assertEqual(body.get("store_url"), "")
        self.assertEqual(body.get("attempted_store_urls"), [])
        self.assertFalse(body.get("degraded"))
        self.assertEqual(body.get("warning"), "")

    async def test_marketplace_sync_hides_hidden_and_scaffold_rows(self):
        payload = {
            "ok": True,
            "generated_at": "2026-03-27T00:00:00Z",
            "plugins": [
                {
                    "id": "life-manager",
                    "plugin_id": "life-manager",
                    "display_name": "Life Manager",
                    "description": "Installable plugin",
                    "category": "productivity",
                    "categories": ["productivity"],
                    "tags": ["productivity"],
                    "marketplace_type": "command_center",
                    "version": "1.0.0",
                    "installable": True,
                    "availability": "installable",
                },
                {
                    "id": "catalog-only-pack",
                    "plugin_id": "catalog-only-pack",
                    "display_name": "Catalog Only Pack",
                    "description": "Inventory only",
                    "category": "alerts",
                    "categories": ["alerts"],
                    "tags": ["alerts"],
                    "marketplace_type": "plugin",
                    "version": "1.0.0",
                    "installable": False,
                    "availability": "catalog_only",
                },
                {
                    "id": "proxy-pack",
                    "plugin_id": "proxy-pack",
                    "display_name": "Proxy Pack",
                    "description": "proxy/noop placeholder",
                    "category": "alerts",
                    "categories": ["alerts"],
                    "tags": ["proxy"],
                    "marketplace_type": "plugin",
                    "version": "1.0.0",
                    "installable": False,
                    "availability": "scaffold",
                },
                {
                    "id": "hidden-pack",
                    "plugin_id": "hidden-pack",
                    "display_name": "Hidden Pack",
                    "description": "suppressed row",
                    "category": "alerts",
                    "categories": ["alerts"],
                    "tags": ["alerts"],
                    "marketplace_type": "plugin",
                    "version": "1.0.0",
                    "installable": False,
                    "availability": "hidden",
                },
            ],
        }

        with _hosted_marketplace_catalog(payload) as store_url:
            response = await self.client.get(f"/api/marketplace/sync?store={store_url}")
            self.assertEqual(response.status, 200)
            body = await response.json()

        rows = body.get("plugins") or []
        ids = [str(row.get("id") or "") for row in rows]
        self.assertEqual(ids, ["life-manager", "catalog-only-pack"])
        self.assertEqual(body.get("total"), 2)


def test_default_marketplace_store_url_requires_explicit_api_origin(monkeypatch):
    monkeypatch.delenv("THOMAS_MARKETPLACE_STORE_URL", raising=False)
    monkeypatch.delenv("SITE_URL", raising=False)

    assert marketplace_routes._default_marketplace_store_url() == ""
