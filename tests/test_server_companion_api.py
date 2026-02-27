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


def _write_signed_bundle(tmp_path: Path, *, secret: str, version: str = "0.1.0") -> Path:
    bundle_dir = tmp_path / f"bundle-{version}"
    payload_file = bundle_dir / "payload" / "modules" / "companion.home" / "ui" / "screen.json"
    payload_file.parent.mkdir(parents=True, exist_ok=True)
    payload_file.write_text(json.dumps({"screen": "home", "version": version}) + "\n", encoding="utf-8")
    sha = hashlib.sha256(payload_file.read_bytes()).hexdigest()
    manifest = {
        "schema_version": 1,
        "bundle_id": f"companion.home-{version}",
        "created_at": "2026-02-20T00:00:00+00:00",
        "min_kernel_version": "0.1.0",
        "module": {
            "id": "companion.home",
            "version": version,
            "entrypoint": "modules/companion.home/ui/screen.json",
            "slots": ["home.main"],
            "permissions": ["storage.read", "ui.render"],
            "ui_schema_version": "0.1.0",
            "display_name": "Home",
            "description": "starter",
        },
        "files": [{"path": "modules/companion.home/ui/screen.json", "sha256": sha}],
        "release_notes": "starter",
    }
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
    manifest["signature"] = {"algo": "hmac-sha256", "value": sig}
    (bundle_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return bundle_dir


class TestServerCompanionApiLocal(AioHTTPTestCase):
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

    async def test_companion_status_contract_and_module_flow(self):
        status_resp = await self.client.get("/api/companion/v1/status")
        self.assertEqual(status_resp.status, 200)
        status_data = await status_resp.json()
        self.assertTrue(status_data.get("ok"))
        self.assertEqual(status_data.get("api_version"), "v1")
        self.assertEqual((status_data.get("kernel") or {}).get("kernel_version"), "0.1.0")
        self.assertIn(
            "pushing companion apps",
            str((status_data.get("mission") or {}).get("primary_function") or ""),
        )

        contract_resp = await self.client.get("/api/companion/v1/contract")
        self.assertEqual(contract_resp.status, 200)
        contract_data = await contract_resp.json()
        self.assertTrue(contract_data.get("ok"))
        self.assertIn("immutable_kernel_boundary", contract_data.get("minimum_requirements") or [])
        self.assertIn("app_store_discovery", contract_data.get("minimum_requirements") or [])
        self.assertIn("ui.render", contract_data.get("permission_allowlist") or [])

        capabilities_resp = await self.client.get("/api/companion/v1/studio/capabilities")
        self.assertEqual(capabilities_resp.status, 200)
        capabilities_data = await capabilities_resp.json()
        self.assertTrue(capabilities_data.get("ok"))
        self.assertIn("ui.render", capabilities_data.get("permission_allowlist") or [])
        self.assertIn("home.main", capabilities_data.get("default_slots") or [])
        self.assertIn("headless_web_runtime", capabilities_data.get("data_primitives") or [])
        self.assertIn("push_release_to_device", capabilities_data.get("action_primitives") or [])
        self.assertTrue((capabilities_data.get("release_controls") or {}).get("supports_device_pinning"))
        self.assertTrue((capabilities_data.get("release_controls") or {}).get("supports_compliance_check"))

        profiles_resp = await self.client.get("/api/companion/v1/policy/profiles")
        self.assertEqual(profiles_resp.status, 200)
        profiles_data = await profiles_resp.json()
        self.assertTrue(profiles_data.get("ok"))
        self.assertGreaterEqual(int(profiles_data.get("count", 0)), 1)

        modules_resp = await self.client.get("/api/companion/v1/modules")
        self.assertEqual(modules_resp.status, 200)
        modules_data = await modules_resp.json()
        self.assertEqual(int(modules_data.get("count", -1)), 0)

        studio_resp = await self.client.post(
            "/api/companion/v1/studio/build-bundle",
            headers={"X-Companion-Peer": "builder.owner.ts.net"},
            json={
                "module": {
                    "id": "companion.studio",
                    "version": "0.1.0",
                    "entrypoint": "modules/companion.studio/ui/screen.json",
                    "slots": ["home.main"],
                    "permissions": ["ui.render", "storage.read"],
                    "ui_schema_version": "0.1.0",
                    "display_name": "Studio",
                    "description": "studio build",
                },
                "screen_payload": {"screen": "studio-home"},
                "release_notes": "studio build",
            },
        )
        self.assertEqual(studio_resp.status, 200)
        studio_data = await studio_resp.json()
        self.assertTrue(studio_data.get("ok"))
        self.assertTrue(Path(str(studio_data.get("bundle_dir") or "")).exists())

        bundle_dir = _write_signed_bundle(Path(self._tmpdir.name), secret="topsecret")
        preview_resp = await self.client.post(
            "/api/companion/v1/bundles/preview",
            headers={"X-Companion-Peer": "builder.owner.ts.net"},
            json={"bundle_dir": str(bundle_dir), "actor": "owner"},
        )
        self.assertEqual(preview_resp.status, 200)
        preview_data = await preview_resp.json()
        self.assertTrue(preview_data.get("ok"))
        preview_slots = (preview_data.get("preview") or {}).get("slots") or {}
        self.assertIn("home.main", preview_slots)

        verify_resp = await self.client.post(
            "/api/companion/v1/bundles/verify",
            json={"bundle_dir": str(bundle_dir)},
        )
        self.assertEqual(verify_resp.status, 200)
        verify_data = await verify_resp.json()
        self.assertTrue(verify_data.get("ok"))

        apply_resp = await self.client.post(
            "/api/companion/v1/bundles/apply",
            json={"bundle_dir": str(bundle_dir), "execute": True},
        )
        self.assertEqual(apply_resp.status, 200)
        apply_data = await apply_resp.json()
        self.assertTrue(apply_data.get("ok"))
        self.assertFalse(bool(apply_data.get("dry_run")))

        modules_resp_2 = await self.client.get("/api/companion/v1/modules")
        self.assertEqual(modules_resp_2.status, 200)
        modules_data_2 = await modules_resp_2.json()
        self.assertEqual(int(modules_data_2.get("count", 0)), 1)
        rows = modules_data_2.get("modules") or []
        self.assertEqual(rows[0].get("module_id"), "companion.home")
        self.assertEqual(rows[0].get("status"), "enabled")

        slots_resp = await self.client.get("/api/companion/v1/slots")
        self.assertEqual(slots_resp.status, 200)
        slots_data = await slots_resp.json()
        slot_home = (slots_data.get("slots") or {}).get("home.main") or []
        self.assertEqual(len(slot_home), 1)
        self.assertEqual(slot_home[0].get("module_id"), "companion.home")

        slot_get_resp = await self.client.get("/api/companion/v1/slots/home.main")
        self.assertEqual(slot_get_resp.status, 200)
        slot_get_data = await slot_get_resp.json()
        self.assertTrue(slot_get_data.get("ok"))
        self.assertEqual(int(slot_get_data.get("count", 0)), 1)
        self.assertEqual(
            ((slot_get_data.get("widgets") or [{}])[0].get("payload") or {}).get("screen"),
            "home",
        )

        bootstrap_resp = await self.client.get("/api/companion/v1/bootstrap?include_slot_payloads=1")
        self.assertEqual(bootstrap_resp.status, 200)
        bootstrap_data = await bootstrap_resp.json()
        self.assertTrue(bootstrap_data.get("ok"))
        payloads = bootstrap_data.get("slot_payloads") or {}
        self.assertIn("home.main", payloads)
        self.assertEqual(int((payloads["home.main"] or {}).get("count", 0)), 1)
        self.assertIn(
            "push_and_apply",
            {
                str(s.get("id") or "")
                for s in list(((bootstrap_data.get("mission") or {}).get("setup") or {}).get("steps") or [])
            },
        )
        self.assertEqual(
            str((bootstrap_data.get("app_store") or {}).get("catalog_endpoint") or ""),
            "/api/companion/v1/app-store",
        )

        register_resp = await self.client.post(
            "/api/companion/v1/devices/register",
            headers={"X-Companion-Peer": "iphone.owner.ts.net"},
            json={
                "device_id": "ios-1",
                "platform": "ios",
                "distribution_channel": "app_store",
                "storefront_region": "US",
                "app_build_id": "ios-build-1",
                "app_version": "1.0.0",
                "channel": "stable",
                "installed_modules": {"companion.home": "0.0.1"},
            },
        )
        self.assertEqual(register_resp.status, 200)
        register_data = await register_resp.json()
        self.assertTrue(register_data.get("ok"))
        self.assertEqual((register_data.get("device") or {}).get("device_id"), "ios-1")
        self.assertEqual((register_data.get("device") or {}).get("policy_profile"), "ios_app_store")

        compliance_resp = await self.client.post(
            "/api/companion/v1/compliance/check",
            headers={"X-Companion-Peer": "laptop.owner.ts.net"},
            json={
                "bundle_dir": str(bundle_dir),
                "platform": "ios",
                "distribution_channel": "app_store",
                "storefront_region": "US",
                "commerce_model": "physical_or_off_app",
            },
        )
        self.assertEqual(compliance_resp.status, 200)
        compliance_data = await compliance_resp.json()
        self.assertTrue(compliance_data.get("ok"))
        self.assertTrue((compliance_data.get("compliance") or {}).get("ok"))

        publish_resp = await self.client.post(
            "/api/companion/v1/releases/publish",
            headers={"X-Companion-Peer": "laptop.owner.ts.net"},
            json={
                "bundle_dir": str(bundle_dir),
                "channel": "stable",
                "actor": "owner",
                "platform": "ios",
                "distribution_channel": "app_store",
                "storefront_region": "US",
                "commerce_model": "physical_or_off_app",
            },
        )
        self.assertEqual(publish_resp.status, 200)
        publish_data = await publish_resp.json()
        self.assertTrue(publish_data.get("ok"))
        self.assertEqual(((publish_data.get("release") or {}).get("module_id")), "companion.home")
        self.assertEqual(((publish_data.get("release") or {}).get("policy_profile_id")), "ios_app_store")
        self.assertTrue(bool((publish_data.get("release") or {}).get("compliance_report_id") or ""))
        release_id = str((publish_data.get("release") or {}).get("release_id") or "")
        self.assertTrue(bool(release_id))

        app_store_resp = await self.client.get(
            "/api/companion/v1/app-store?channel=stable&device_id=ios-1&include_ineligible=0",
        )
        self.assertEqual(app_store_resp.status, 200)
        app_store_data = await app_store_resp.json()
        self.assertTrue(app_store_data.get("ok"))
        app_rows = list(app_store_data.get("apps") or [])
        self.assertGreaterEqual(len(app_rows), 1)
        self.assertIn("companion.home", {str(item.get("module_id") or "") for item in app_rows})
        home_row = next(
            (item for item in app_rows if str(item.get("module_id") or "") == "companion.home"),
            {},
        )
        self.assertTrue(bool((home_row.get("compatibility") or {}).get("eligible")))
        self.assertIn(
            "/devices/ios-1/apps/companion.home/push", str((home_row.get("install") or {}).get("push_endpoint") or "")
        )

        push_preview_resp = await self.client.post(
            "/api/companion/v1/devices/ios-1/apps/companion.home/push",
            headers={"X-Companion-Peer": "iphone.owner.ts.net"},
            json={"actor": "owner", "channel": "stable", "execute": False},
        )
        self.assertEqual(push_preview_resp.status, 200)
        push_preview_data = await push_preview_resp.json()
        self.assertTrue(push_preview_data.get("ok"))
        self.assertTrue(bool(push_preview_data.get("planned")))
        self.assertEqual(
            str((push_preview_data.get("release") or {}).get("release_id") or ""),
            release_id,
        )

        publish_blocked_resp = await self.client.post(
            "/api/companion/v1/releases/publish",
            headers={"X-Companion-Peer": "laptop.owner.ts.net"},
            json={
                "bundle_dir": str(bundle_dir),
                "channel": "stable",
                "actor": "owner",
                "platform": "ios",
                "distribution_channel": "app_store",
                "storefront_region": "US",
                "commerce_model": "digital_in_app",
                "store_billing_enabled": False,
            },
        )
        self.assertEqual(publish_blocked_resp.status, 400)
        publish_blocked_data = await publish_blocked_resp.json()
        self.assertFalse(bool(publish_blocked_data.get("ok")))
        compliance_blocked = (publish_blocked_data.get("compliance") or {}).get("report") or {}
        codes = {str(item.get("code") or "") for item in list(compliance_blocked.get("violations") or [])}
        self.assertIn("commerce.store_billing_required", codes)

        publish_missing_region_resp = await self.client.post(
            "/api/companion/v1/releases/publish",
            headers={"X-Companion-Peer": "laptop.owner.ts.net"},
            json={
                "bundle_dir": str(bundle_dir),
                "channel": "stable",
                "actor": "owner",
                "platform": "ios",
                "distribution_channel": "app_store",
                "commerce_model": "physical_or_off_app",
            },
        )
        self.assertEqual(publish_missing_region_resp.status, 400)
        publish_missing_region_data = await publish_missing_region_resp.json()
        profile_report = (publish_missing_region_data.get("compliance") or {}).get("report") or {}
        missing_codes = {str(item.get("code") or "") for item in list(profile_report.get("violations") or [])}
        self.assertIn("targeting.storefront_region_required", missing_codes)

        release_get_resp = await self.client.get(
            f"/api/companion/v1/releases/{release_id}",
        )
        self.assertEqual(release_get_resp.status, 200)
        release_get_data = await release_get_resp.json()
        self.assertTrue(release_get_data.get("ok"))
        self.assertEqual(((release_get_data.get("release") or {}).get("release_id")), release_id)

        release_manifest_resp = await self.client.get(
            f"/api/companion/v1/releases/{release_id}/manifest",
        )
        self.assertEqual(release_manifest_resp.status, 200)
        release_manifest_data = await release_manifest_resp.json()
        self.assertTrue(release_manifest_data.get("ok"))
        self.assertEqual(
            (((release_manifest_data.get("manifest") or {}).get("module") or {}).get("version")),
            "0.1.0",
        )

        release_download_resp = await self.client.get(
            f"/api/companion/v1/releases/{release_id}/download",
        )
        self.assertEqual(release_download_resp.status, 200)
        self.assertEqual(release_download_resp.headers.get("Content-Type"), "application/zip")
        release_zip = await release_download_resp.read()
        self.assertGreaterEqual(len(release_zip), 100)
        self.assertTrue(release_zip.startswith(b"PK"))

        check_resp = await self.client.post(
            "/api/companion/v1/devices/ios-1/updates/check",
            headers={"X-Companion-Peer": "iphone.owner.ts.net"},
            json={"channel": "stable"},
        )
        self.assertEqual(check_resp.status, 200)
        check_data = await check_resp.json()
        self.assertEqual(int(check_data.get("count", -1)), 1)

        heartbeat_resp = await self.client.post(
            "/api/companion/v1/devices/ios-1/heartbeat",
            headers={"X-Companion-Peer": "iphone.owner.ts.net"},
            json={"installed_modules": {"companion.home": "0.1.0"}},
        )
        self.assertEqual(heartbeat_resp.status, 200)

        check_resp_2 = await self.client.post(
            "/api/companion/v1/devices/ios-1/updates/check",
            headers={"X-Companion-Peer": "iphone.owner.ts.net"},
            json={"channel": "stable"},
        )
        self.assertEqual(check_resp_2.status, 200)
        check_data_2 = await check_resp_2.json()
        self.assertEqual(int(check_data_2.get("count", -1)), 0)

        bundle_dir_2 = _write_signed_bundle(Path(self._tmpdir.name), secret="topsecret", version="0.2.0")
        ship_resp = await self.client.post(
            "/api/companion/v1/ship",
            headers={"X-Companion-Peer": "laptop.owner.ts.net"},
            json={"bundle_dir": str(bundle_dir_2), "channel": "stable", "actor": "owner", "execute": True},
        )
        self.assertEqual(ship_resp.status, 200)
        ship_data = await ship_resp.json()
        self.assertTrue(ship_data.get("ok"))
        self.assertEqual((((ship_data.get("release") or {}).get("release") or {}).get("module_version")), "0.2.0")

        check_resp_3 = await self.client.post(
            "/api/companion/v1/devices/ios-1/updates/check",
            headers={"X-Companion-Peer": "iphone.owner.ts.net"},
            json={"channel": "stable"},
        )
        self.assertEqual(check_resp_3.status, 200)
        check_data_3 = await check_resp_3.json()
        self.assertEqual(int(check_data_3.get("count", -1)), 1)

        release_id_latest = str(((ship_data.get("release") or {}).get("release") or {}).get("release_id") or "")
        self.assertTrue(bool(release_id_latest))

        rollout_resp = await self.client.post(
            f"/api/companion/v1/releases/{release_id_latest}/rollout",
            headers={"X-Companion-Peer": "laptop.owner.ts.net"},
            json={"rollout_pct": 0, "actor": "owner"},
        )
        self.assertEqual(rollout_resp.status, 200)
        rollout_data = await rollout_resp.json()
        self.assertTrue(rollout_data.get("ok"))
        self.assertEqual((rollout_data.get("release") or {}).get("rollout_pct"), 0)

        check_resp_4 = await self.client.post(
            "/api/companion/v1/devices/ios-1/updates/check",
            headers={"X-Companion-Peer": "iphone.owner.ts.net"},
            json={"channel": "stable"},
        )
        self.assertEqual(check_resp_4.status, 200)
        check_data_4 = await check_resp_4.json()
        self.assertEqual(int(check_data_4.get("count", -1)), 0)

        pin_resp = await self.client.post(
            "/api/companion/v1/devices/ios-1/pin-release",
            headers={"X-Companion-Peer": "iphone.owner.ts.net"},
            json={"release_id": release_id_latest, "actor": "owner"},
        )
        self.assertEqual(pin_resp.status, 200)
        pin_data = await pin_resp.json()
        self.assertTrue(pin_data.get("ok"))
        self.assertEqual((pin_data.get("device") or {}).get("pinned_release_id"), release_id_latest)

        check_resp_5 = await self.client.post(
            "/api/companion/v1/devices/ios-1/updates/check",
            headers={"X-Companion-Peer": "iphone.owner.ts.net"},
            json={"channel": "stable"},
        )
        self.assertEqual(check_resp_5.status, 200)
        check_data_5 = await check_resp_5.json()
        self.assertEqual(str(check_data_5.get("source") or ""), "pinned")
        self.assertEqual(int(check_data_5.get("count", -1)), 1)

        unpin_resp = await self.client.post(
            "/api/companion/v1/devices/ios-1/unpin-release",
            headers={"X-Companion-Peer": "iphone.owner.ts.net"},
            json={"actor": "owner"},
        )
        self.assertEqual(unpin_resp.status, 200)
        unpin_data = await unpin_resp.json()
        self.assertTrue(unpin_data.get("ok"))
        self.assertEqual((unpin_data.get("device") or {}).get("pinned_release_id"), "")

        promote_resp = await self.client.post(
            f"/api/companion/v1/releases/{release_id_latest}/promote",
            headers={"X-Companion-Peer": "laptop.owner.ts.net"},
            json={"channel": "beta", "actor": "owner"},
        )
        self.assertEqual(promote_resp.status, 200)
        promote_data = await promote_resp.json()
        self.assertTrue(promote_data.get("ok"))
        self.assertEqual(((promote_data.get("release") or {}).get("channel")), "beta")

        rollback_resp = await self.client.post(
            f"/api/companion/v1/releases/{release_id_latest}/rollback",
            headers={"X-Companion-Peer": "laptop.owner.ts.net"},
            json={"channel": "stable", "actor": "owner"},
        )
        self.assertEqual(rollback_resp.status, 200)
        rollback_data = await rollback_resp.json()
        self.assertTrue(rollback_data.get("ok"))
        self.assertEqual(((rollback_data.get("release") or {}).get("channel")), "stable")

        releases_resp = await self.client.get("/api/companion/v1/releases?channel=stable")
        self.assertEqual(releases_resp.status, 200)
        releases_data = await releases_resp.json()
        self.assertGreaterEqual(int(releases_data.get("count", 0)), 1)

        devices_resp = await self.client.get(
            "/api/companion/v1/devices",
            headers={"X-Companion-Peer": "owner.ts.net"},
        )
        self.assertEqual(devices_resp.status, 200)
        devices_data = await devices_resp.json()
        self.assertGreaterEqual(int(devices_data.get("count", 0)), 1)

        audit_resp = await self.client.get("/api/companion/v1/audit/events?limit=100")
        self.assertEqual(audit_resp.status, 200)
        audit_data = await audit_resp.json()
        event_types = {str(item.get("event_type")) for item in list(audit_data.get("events") or [])}
        self.assertIn("release.publish", event_types)
        self.assertIn("device.register", event_types)

        disable_resp = await self.client.post("/api/companion/v1/modules/companion.home/disable")
        self.assertEqual(disable_resp.status, 200)
        disable_data = await disable_resp.json()
        self.assertTrue(disable_data.get("ok"))
        self.assertEqual((disable_data.get("module") or {}).get("status"), "disabled")

        slots_resp_2 = await self.client.get("/api/companion/v1/slots")
        self.assertEqual(slots_resp_2.status, 200)
        slots_data_2 = await slots_resp_2.json()
        self.assertEqual(int(slots_data_2.get("enabled_modules", -1)), 0)
        self.assertEqual((slots_data_2.get("slots") or {}).get("home.main"), None)


class TestServerCompanionApiRemoteAuth(AioHTTPTestCase):
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

    async def test_companion_status_requires_remote_token(self):
        no_auth = await self.client.get("/api/companion/v1/status")
        self.assertEqual(no_auth.status, 401)

        with_auth = await self.client.get(
            "/api/companion/v1/status",
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(with_auth.status, 200)

    async def test_companion_mutation_routes_enforce_tailscale_identity(self):
        forbidden = await self.client.post(
            "/api/companion/v1/bundles/verify",
            headers={
                "Authorization": "Bearer test-token",
                "X-Companion-Peer": "internet.example",
            },
            json={"bundle_dir": self._tmpdir.name},
        )
        self.assertEqual(forbidden.status, 403)

        allowed_peer = await self.client.post(
            "/api/companion/v1/bundles/verify",
            headers={
                "Authorization": "Bearer test-token",
                "X-Companion-Peer": "device.tailnet.ts.net",
            },
            json={"bundle_dir": self._tmpdir.name},
        )
        self.assertNotEqual(allowed_peer.status, 403)

        forbidden_ship = await self.client.post(
            "/api/companion/v1/ship",
            headers={
                "Authorization": "Bearer test-token",
                "X-Companion-Peer": "internet.example",
            },
            json={"bundle_dir": self._tmpdir.name, "channel": "stable", "execute": False},
        )
        self.assertEqual(forbidden_ship.status, 403)

        forbidden_register = await self.client.post(
            "/api/companion/v1/devices/register",
            headers={
                "Authorization": "Bearer test-token",
                "X-Companion-Peer": "internet.example",
            },
            json={"device_id": "ios-remote"},
        )
        self.assertEqual(forbidden_register.status, 403)

        forbidden_push = await self.client.post(
            "/api/companion/v1/devices/ios-remote/apps/companion.home/push",
            headers={
                "Authorization": "Bearer test-token",
                "X-Companion-Peer": "internet.example",
            },
            json={"channel": "stable"},
        )
        self.assertEqual(forbidden_push.status, 403)

        allowed_push = await self.client.post(
            "/api/companion/v1/devices/ios-remote/apps/companion.home/push",
            headers={
                "Authorization": "Bearer test-token",
                "X-Companion-Peer": "ios.user.ts.net",
            },
            json={"channel": "stable"},
        )
        self.assertNotEqual(allowed_push.status, 403)

        allowed_register = await self.client.post(
            "/api/companion/v1/devices/register",
            headers={
                "Authorization": "Bearer test-token",
                "X-Companion-Peer": "ios.user.ts.net",
            },
            json={
                "device_id": "ios-remote",
                "platform": "ios",
                "channel": "stable",
            },
        )
        self.assertEqual(allowed_register.status, 200)


if __name__ == "__main__":
    unittest.main()
