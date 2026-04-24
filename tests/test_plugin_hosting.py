from __future__ import annotations

import hashlib
import json
import tempfile
import zipfile
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from thomas.server.desktop_plugins import build_plugin_install_deep_link, parse_plugin_install_deep_link
from thomas.server.routes import plugin_hosting


def _write_bundle(plugin_dir: Path, files: dict[str, str]) -> tuple[str, int]:
    bundle_path = plugin_dir / "bundle.zip"
    with zipfile.ZipFile(bundle_path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    digest = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    return digest, bundle_path.stat().st_size


def _write_manifest(
    plugin_dir: Path,
    *,
    plugin_id: str,
    sha256: str,
    size_bytes: int,
    publisher_id: str = "unknown-publisher",
    publisher_name: str = "Unknown Publisher",
    signature: str = "",
    marketplace_type: str = "command_center",
    requires: list[str] | None = None,
    left_nav_behavior: str = "workspace",
) -> None:
    manifest = {
        "id": plugin_id,
        "plugin_id": plugin_id,
        "title": plugin_id,
        "display_name": plugin_id,
        "description": "test plugin",
        "version": "1.0.0",
        "author": "tests",
        "source": publisher_name,
        "section": "apps",
        "sha256": sha256,
        "size_bytes": size_bytes,
        "publisher_id": publisher_id,
        "publisher_name": publisher_name,
        "signature": signature,
        "kind": "desktop_plugin",
        "marketplace_type": marketplace_type,
        "category": "productivity",
        "categories": ["productivity", "automation"],
        "tags": ["test", marketplace_type],
        "requires": requires or [],
        "left_nav_behavior": left_nav_behavior,
        "default_nav_section": "command_centers" if left_nav_behavior == "workspace" else "installed",
        "default_nav_order": 420 if left_nav_behavior == "workspace" else 920,
        "mode_id": plugin_id.replace("-", "_"),
        "api_namespace": plugin_id,
        "surface": {
            "entry_html": "web/index.html",
            "title": plugin_id,
            "surface_mode": "immersive",
        },
        "verified": publisher_id == "thomas-official",
        "capabilities": ["test.capability"],
    }
    (plugin_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _build_registry(
    tmp_path: Path,
    *,
    plugin_id: str,
    files: dict[str, str],
    publisher_id: str = "unknown-publisher",
    publisher_name: str = "Unknown Publisher",
    signature: str = "",
) -> plugin_hosting.PluginRegistry:
    storage_dir = tmp_path / "registry"
    registry = plugin_hosting.PluginRegistry(storage_dir)
    registry.ensure_storage()
    plugin_dir = storage_dir / "plugins" / plugin_id
    plugin_dir.mkdir(parents=True, exist_ok=True)
    sha256, size_bytes = _write_bundle(plugin_dir, files)
    _write_manifest(
        plugin_dir,
        plugin_id=plugin_id,
        sha256=sha256,
        size_bytes=size_bytes,
        publisher_id=publisher_id,
        publisher_name=publisher_name,
        signature=signature,
    )
    return registry


class TestPluginHostingRoutes(AioHTTPTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._previous_registry = plugin_hosting._registry
        self._previous_storage_dir = plugin_hosting.PLUGIN_STORAGE_DIR
        self._previous_download_tokens = dict(plugin_hosting._DOWNLOAD_TOKENS)

    def tearDown(self) -> None:
        try:
            plugin_hosting._registry = self._previous_registry
            plugin_hosting.PLUGIN_STORAGE_DIR = self._previous_storage_dir
            plugin_hosting._DOWNLOAD_TOKENS.clear()
            plugin_hosting._DOWNLOAD_TOKENS.update(self._previous_download_tokens)
            self._tmpdir.cleanup()
        finally:
            super().tearDown()

    async def get_application(self):
        storage_dir = Path(self._tmpdir.name) / "registry"
        registry = plugin_hosting.PluginRegistry(storage_dir)
        registry.ensure_storage()

        trusted_dir = storage_dir / "plugins" / "life-manager"
        trusted_dir.mkdir(parents=True, exist_ok=True)
        trusted_sha, trusted_size = _write_bundle(trusted_dir, {"web/index.html": "<html>life</html>"})
        _write_manifest(
            trusted_dir,
            plugin_id="life-manager",
            sha256=trusted_sha,
            size_bytes=trusted_size,
            publisher_id="thomas-official",
            publisher_name="Thomas",
            signature="official-signature",
            marketplace_type="command_center",
            requires=["life-manager-foundation"],
            left_nav_behavior="workspace",
        )

        hidden_dir = storage_dir / "plugins" / "evil-plugin"
        hidden_dir.mkdir(parents=True, exist_ok=True)
        hidden_sha, hidden_size = _write_bundle(hidden_dir, {"web/index.html": "<html>evil</html>"})
        _write_manifest(
            hidden_dir,
            plugin_id="evil-plugin",
            sha256=hidden_sha,
            size_bytes=hidden_size,
            publisher_id="evil-corp",
            publisher_name="Evil Corp",
            signature="community-signature",
            marketplace_type="plugin",
            requires=[],
            left_nav_behavior="none",
        )

        plugin_hosting.PLUGIN_STORAGE_DIR = storage_dir
        plugin_hosting._SIGNING_SECRET_CACHE = None
        plugin_hosting._registry = registry

        app = web.Application()
        plugin_hosting.register_plugin_hosting_routes(app)
        return app

    async def test_catalog_returns_only_trusted_signed_plugins_with_links(self):
        resp = await self.client.get("/api/v1/plugins/catalog")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        plugins = body.get("plugins") or []
        self.assertEqual(len(plugins), 1)
        plugin = plugins[0]
        self.assertEqual(plugin.get("id"), "life-manager")
        self.assertEqual(plugin.get("marketplace_type"), "command_center")
        self.assertEqual(plugin.get("left_nav_behavior"), "workspace")
        self.assertEqual(plugin.get("requires"), ["life-manager-foundation"])
        self.assertTrue(
            str(plugin.get("manual_download_url") or "").endswith("/api/v1/plugins/life-manager/manual-download")
        )
        parsed = parse_plugin_install_deep_link(str(plugin.get("open_in_thomas_url") or ""))
        self.assertEqual(parsed.get("plugin_id"), "life-manager")
        self.assertEqual(parsed.get("channel"), "stable")
        self.assertTrue(str(parsed.get("store") or "").startswith("http://127.0.0.1:"))

    async def test_detail_hides_untrusted_plugins(self):
        resp = await self.client.get("/api/v1/plugins/evil-plugin")
        self.assertEqual(resp.status, 404)

    async def test_detail_returns_open_in_thomas_and_manual_download_for_trusted_plugin(self):
        resp = await self.client.get("/api/v1/plugins/life-manager")
        self.assertEqual(resp.status, 200)
        plugin = await resp.json()
        self.assertEqual(plugin.get("marketplace_type"), "command_center")
        self.assertEqual(plugin.get("categories"), ["productivity", "automation"])
        self.assertEqual(plugin.get("requires"), ["life-manager-foundation"])
        self.assertTrue(
            str(plugin.get("manual_download_url") or "").endswith("/api/v1/plugins/life-manager/manual-download")
        )
        parsed = parse_plugin_install_deep_link(str(plugin.get("open_in_thomas_url") or ""))
        self.assertEqual(parsed.get("plugin_id"), "life-manager")
        self.assertEqual(parsed.get("channel"), "stable")

    async def test_download_token_requires_api_key_and_returns_bundle_metadata(self):
        missing_key = await self.client.post("/api/v1/plugins/download-token", json={"plugin_id": "life-manager"})
        self.assertEqual(missing_key.status, 401)

        resp = await self.client.post(
            "/api/v1/plugins/download-token",
            json={"plugin_id": "life-manager"},
            headers={"X-Thomas-API-Key": "local-dev-install-key"},
        )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertIn("download_url", body)
        self.assertTrue(str(body.get("sha256") or "").strip())

    async def test_manual_download_redirects_to_signed_bundle_route(self):
        resp = await self.client.get("/api/v1/plugins/life-manager/manual-download", allow_redirects=False)
        self.assertEqual(resp.status, 302)
        self.assertIn("/api/v1/plugins/download/", resp.headers.get("Location", ""))

    async def test_manual_and_automatic_download_share_bundle_checksum(self):
        detail_resp = await self.client.get("/api/v1/plugins/life-manager")
        self.assertEqual(detail_resp.status, 200)
        plugin = await detail_resp.json()

        token_resp = await self.client.post(
            "/api/v1/plugins/download-token",
            json={"plugin_id": "life-manager"},
            headers={"X-Thomas-API-Key": "local-dev-install-key"},
        )
        self.assertEqual(token_resp.status, 200)
        token_body = await token_resp.json()
        self.assertEqual(plugin.get("sha256"), token_body.get("sha256"))


def test_verify_bundle_rejects_disallowed_pattern(tmp_path: Path) -> None:
    registry = _build_registry(
        tmp_path,
        plugin_id="unsafe-plugin",
        files={"main.py": 'print(eval("1+1"))\n'},
    )

    result = registry.verify_bundle("unsafe-plugin")

    assert result["valid"] is False
    assert result["error"] == "Bundle content failed security scan"
    assert result["entry"] == "main.py"
    assert result["pattern"] == "eval("


def test_verify_bundle_accepts_clean_bundle(tmp_path: Path) -> None:
    registry = _build_registry(
        tmp_path,
        plugin_id="safe-plugin",
        files={"main.py": 'print("safe")\n'},
    )

    result = registry.verify_bundle("safe-plugin")

    assert result["valid"] is True
    assert "sha256" in result


def test_download_tokens_are_memory_only_and_expire(monkeypatch) -> None:
    now = int(plugin_hosting.time.time())
    token = plugin_hosting._issue_download_token("life-manager", now + 60)

    assert plugin_hosting._verify_token(token)["plugin_id"] == "life-manager"

    monkeypatch.setattr(plugin_hosting.time, "time", lambda: now + 61)

    assert plugin_hosting._verify_token(token) is None
    assert token not in plugin_hosting._DOWNLOAD_TOKENS


def test_parse_plugin_install_deep_link_roundtrip() -> None:
    link = build_plugin_install_deep_link("life-manager", "https://github.com/Calvin-Corbett/thomas", channel="stable")
    parsed = parse_plugin_install_deep_link(link)

    assert parsed == {
        "plugin_id": "life-manager",
        "store": "https://github.com/Calvin-Corbett/thomas",
        "channel": "stable",
    }


def test_parse_plugin_install_deep_link_rejects_invalid_inputs() -> None:
    invalid_links = [
        "https://example.invalid/plugins/life-manager",
        "thomas://open-plugin?plugin_id=life-manager&store=https%3A%2F%2Fexample.invalid",
        "thomas://install-plugin?store=https%3A%2F%2Fexample.invalid",
        "thomas://install-plugin?plugin_id=life-manager",
        "thomas://install-plugin?plugin_id=life-manager&store=https%3A%2F%2Fexample.invalid",
    ]

    for link in invalid_links:
        try:
            parse_plugin_install_deep_link(link)
        except ValueError:
            continue
        raise AssertionError(f"Expected ValueError for {link!r}")
