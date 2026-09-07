"""End-to-end tests for the companion surface host and bridge API."""

import hashlib
import hmac
import json
import os
import tempfile
import unittest
from pathlib import Path

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app

SURFACE_HTML = "<html><head><title>Fit</title></head><body><div id=app></div></body></html>\n"


def _write_surface_bundle(
    tmp_path: Path,
    *,
    secret: str,
    permissions: list[str],
    surface_type: str = "surface",
    module_id: str = "fit.tracker",
) -> Path:
    bundle_dir = tmp_path / f"bundle-{module_id}-{surface_type}"
    # A declarative module must ship a JSON component tree; a surface ships HTML.
    # The policy validator enforces that pairing, so the fixture has to honour it.
    if surface_type == "surface":
        rel = f"modules/{module_id}/ui/screen.html"
        body = SURFACE_HTML
    else:
        rel = f"modules/{module_id}/ui/screen.json"
        body = json.dumps({"screen": "home", "components": [{"type": "text", "value": "hi"}]}) + "\n"
    payload_file = bundle_dir / "payload" / Path(rel)
    payload_file.parent.mkdir(parents=True, exist_ok=True)
    payload_file.write_text(body, encoding="utf-8")
    sha = hashlib.sha256(payload_file.read_bytes()).hexdigest()

    module: dict = {
        "id": module_id,
        "version": "0.1.0",
        "entrypoint": rel,
        "slots": ["home.main"],
        "permissions": sorted(permissions),
        "ui_schema_version": "0.1.0",
        "display_name": "Fit Tracker",
        "description": "surface module",
    }
    # Mirrors ModuleContract.to_dict(): the default is omitted so pre-existing
    # signatures stay valid.
    if surface_type != "declarative":
        module["surface_type"] = surface_type

    manifest = {
        "schema_version": 1,
        "bundle_id": f"{module_id}-0.1.0",
        "created_at": "2026-02-20T00:00:00+00:00",
        "min_kernel_version": "0.1.0",
        "module": module,
        "files": [{"path": rel, "sha256": sha}],
        "release_notes": "surface",
    }
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
    manifest["signature"] = {"algo": "hmac-sha256", "value": sig}
    (bundle_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return bundle_dir


class TestCompanionSurfaceApi(AioHTTPTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory()
        self._old_secret = os.environ.get("THOMAS_COMPANION_UPDATE_SECRET")
        os.environ["THOMAS_COMPANION_UPDATE_SECRET"] = "topsecret"

    def tearDown(self) -> None:
        if self._old_secret is None:
            os.environ.pop("THOMAS_COMPANION_UPDATE_SECRET", None)
        else:
            os.environ["THOMAS_COMPANION_UPDATE_SECRET"] = self._old_secret
        try:
            self._tmpdir.cleanup()
        finally:
            super().tearDown()

    async def get_application(self):
        cfg = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
            memory=MemoryConfig(root=str(Path(self._tmpdir.name) / "runtime")),
            server=ServerConfig(access_mode="local"),
        )
        return create_app(cfg)

    async def _install(self, **kwargs) -> None:
        bundle_dir = _write_surface_bundle(Path(self._tmpdir.name), secret="topsecret", **kwargs)
        resp = await self.client.post(
            "/api/companion/v1/bundles/apply",
            json={"bundle_dir": str(bundle_dir), "execute": True},
        )
        self.assertEqual(resp.status, 200, await resp.text())

    async def test_surface_document_is_served_sandboxed_with_bridge(self):
        await self._install(permissions=["ui.render", "storage.read", "storage.write"])
        resp = await self.client.get("/api/companion/v1/surface/fit.tracker/document")
        self.assertEqual(resp.status, 200)

        csp = resp.headers.get("Content-Security-Policy", "")
        # The frame must have no network of its own — the bridge is the only way out.
        self.assertIn("connect-src 'none'", csp)
        self.assertIn("default-src 'none'", csp)
        self.assertIn("frame-ancestors 'self'", csp)
        self.assertEqual(resp.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(resp.headers.get("Cache-Control"), "no-store")

        body = await resp.text()
        # The shell renders this via srcdoc, which does not inherit response
        # headers, so the policy has to be inside the document too.
        self.assertIn("http-equiv=\"Content-Security-Policy\"", body)
        self.assertIn("connect-src &#39;none&#39;", body)
        self.assertIn("window.thomas", body)
        self.assertIn("__thomasBridge", body)
        # Thomas's design system rides along, so an app that ships no CSS of its
        # own still looks like Thomas rather than like raw HTML.
        self.assertIn("--c-accent:#8b8cff", body)
        self.assertIn(".t-card", body)
        self.assertIn("<div id=app>", body)
        # Shim must land inside <head>, ahead of any app script.
        self.assertLess(body.index("__thomasBridge"), body.index("<div id=app>"))

    async def test_declarative_module_has_no_surface_document(self):
        await self._install(permissions=["ui.render"], surface_type="declarative")
        resp = await self.client.get("/api/companion/v1/surface/fit.tracker/document")
        self.assertEqual(resp.status, 400)

    async def test_unknown_module_is_404(self):
        resp = await self.client.get("/api/companion/v1/surface/nope.module/document")
        self.assertEqual(resp.status, 404)

    async def test_storage_roundtrip_through_the_bridge(self):
        await self._install(permissions=["ui.render", "storage.read", "storage.write"])

        set_resp = await self.client.post(
            "/api/companion/v1/surface/fit.tracker/storage/set",
            json={"key": "workouts", "value": [{"lift": "squat"}]},
        )
        self.assertEqual(set_resp.status, 200, await set_resp.text())

        get_resp = await self.client.post(
            "/api/companion/v1/surface/fit.tracker/storage/get",
            json={"key": "workouts"},
        )
        self.assertEqual(get_resp.status, 200)
        self.assertEqual((await get_resp.json()).get("value"), [{"lift": "squat"}])

        keys_resp = await self.client.get("/api/companion/v1/surface/fit.tracker/storage/keys")
        self.assertEqual(keys_resp.status, 200)
        keys_data = await keys_resp.json()
        self.assertEqual(keys_data.get("keys"), ["workouts"])
        self.assertEqual(keys_data.get("usage", {}).get("key_count"), 1)

        del_resp = await self.client.post(
            "/api/companion/v1/surface/fit.tracker/storage/delete",
            json={"key": "workouts"},
        )
        self.assertEqual(del_resp.status, 200)
        self.assertTrue((await del_resp.json()).get("deleted"))

    async def test_write_requires_declared_permission(self):
        await self._install(permissions=["ui.render", "storage.read"])
        resp = await self.client.post(
            "/api/companion/v1/surface/fit.tracker/storage/set",
            json={"key": "workouts", "value": [1]},
        )
        self.assertEqual(resp.status, 403)

    async def test_read_requires_declared_permission(self):
        await self._install(permissions=["ui.render"])
        resp = await self.client.post(
            "/api/companion/v1/surface/fit.tracker/storage/get",
            json={"key": "workouts"},
        )
        self.assertEqual(resp.status, 403)

    async def test_ask_requires_network_egress(self):
        await self._install(permissions=["ui.render", "storage.read"])
        resp = await self.client.post(
            "/api/companion/v1/surface/fit.tracker/ask",
            json={"prompt": "am I overtraining?"},
        )
        self.assertEqual(resp.status, 403)

    async def test_bad_storage_key_is_rejected(self):
        await self._install(permissions=["ui.render", "storage.read", "storage.write"])
        resp = await self.client.post(
            "/api/companion/v1/surface/fit.tracker/storage/set",
            json={"key": "../escape", "value": 1},
        )
        self.assertEqual(resp.status, 400)

    async def test_disabled_module_is_forbidden(self):
        await self._install(permissions=["ui.render", "storage.read", "storage.write"])
        disable = await self.client.post("/api/companion/v1/modules/fit.tracker/disable")
        self.assertEqual(disable.status, 200, await disable.text())
        resp = await self.client.get("/api/companion/v1/surface/fit.tracker/document")
        self.assertEqual(resp.status, 403)


class TestCompanionSurfaceRemoteAuth(AioHTTPTestCase):
    """The Tailscale configuration: access_mode=remote, bearer token required.

    This is the mode Infinite actually runs in, so the surface document has to be
    reachable here. It is fetched by the shell with an Authorization header and
    handed to the frame via srcdoc, because an iframe navigation cannot carry one
    and putting the token in the URL would expose it to the surface itself.
    """

    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory()
        self._old_secret = os.environ.get("THOMAS_COMPANION_UPDATE_SECRET")
        os.environ["THOMAS_COMPANION_UPDATE_SECRET"] = "topsecret"

    def tearDown(self) -> None:
        if self._old_secret is None:
            os.environ.pop("THOMAS_COMPANION_UPDATE_SECRET", None)
        else:
            os.environ["THOMAS_COMPANION_UPDATE_SECRET"] = self._old_secret
        try:
            self._tmpdir.cleanup()
        finally:
            super().tearDown()

    async def get_application(self):
        cfg = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
            memory=MemoryConfig(root=str(Path(self._tmpdir.name) / "runtime")),
            server=ServerConfig(access_mode="remote", api_token="test-token"),
        )
        return create_app(cfg)

    async def test_surface_document_requires_and_accepts_a_bearer_token(self):
        bundle_dir = _write_surface_bundle(
            Path(self._tmpdir.name),
            secret="topsecret",
            permissions=["ui.render", "storage.read"],
        )
        auth = {"Authorization": "Bearer test-token"}
        applied = await self.client.post(
            "/api/companion/v1/bundles/apply",
            json={"bundle_dir": str(bundle_dir), "execute": True},
            headers=auth,
        )
        self.assertEqual(applied.status, 200, await applied.text())

        # An iframe src would arrive like this — tokenless — and must be refused.
        no_auth = await self.client.get("/api/companion/v1/surface/fit.tracker/document")
        self.assertEqual(no_auth.status, 401)

        # The shell fetch carries the header, which is how srcdoc gets its content.
        with_auth = await self.client.get(
            "/api/companion/v1/surface/fit.tracker/document", headers=auth
        )
        self.assertEqual(with_auth.status, 200)
        self.assertIn("window.thomas", await with_auth.text())


if __name__ == "__main__":
    unittest.main()
