import unittest
from unittest.mock import patch

import aiohttp
from aiohttp.client_exceptions import WSServerHandshakeError
from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app


class TestServerAccessModeLocal(AioHTTPTestCase):
    async def get_application(self):
        cfg = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
            server=ServerConfig(access_mode="local"),
        )
        return create_app(cfg)

    async def test_local_mode_allows_loopback_api_without_token(self):
        resp = await self.client.get("/api/models")
        self.assertEqual(resp.status, 200)

    async def test_model_capabilities_endpoint_returns_profile_map(self):
        resp = await self.client.get("/api/models/capabilities")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("profiles", data)
        self.assertIn("local", data["profiles"])
        self.assertIn("chat", data["profiles"]["local"])

    async def test_setup_bootstrap_endpoint_returns_machine_snapshot(self):
        resp = await self.client.get("/api/setup/bootstrap")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("system", data)
        self.assertIn("tools", data)
        self.assertIn("quick_start", data)

    async def test_setup_repair_route_is_registered(self):
        resp = await self.client.get("/api/setup/repair")
        self.assertEqual(resp.status, 405)

    async def test_setup_repair_endpoint_returns_result_shape(self):
        fake_output = "[thomas] Repair report: C:\\temp\\repair_report.txt\n"
        with patch("thomas.server.app.subprocess.run") as run_mock:
            run_mock.return_value = type(
                "Completed",
                (),
                {"returncode": 0, "stdout": fake_output, "stderr": ""},
            )()
            resp = await self.client.post(
                "/api/setup/repair",
                json={"skip_install": True, "skip_doctor": True, "auto_install_tools": False},
            )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(bool(data.get("ok")))
        self.assertEqual(int(data.get("exit_code", 1)), 0)
        self.assertTrue(str(data.get("report_path") or "").endswith("repair_report.txt"))

    async def test_default_security_headers_are_set(self):
        resp = await self.client.get("/")
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(resp.headers.get("Referrer-Policy"), "strict-origin-when-cross-origin")
        self.assertEqual(resp.headers.get("X-Frame-Options"), "SAMEORIGIN")


class TestServerAccessModeRemote(AioHTTPTestCase):
    async def get_application(self):
        cfg = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
            server=ServerConfig(access_mode="remote", api_token="test-token"),
        )
        return create_app(cfg)

    async def test_remote_mode_requires_token(self):
        no_auth = await self.client.get("/api/models")
        self.assertEqual(no_auth.status, 401)

        bearer = await self.client.get("/api/models", headers={"Authorization": "Bearer test-token"})
        self.assertEqual(bearer.status, 200)

        x_token = await self.client.get("/api/models", headers={"X-Api-Token": "test-token"})
        self.assertEqual(x_token.status, 200)

    async def test_remote_mode_accepts_version_without_token_by_default(self):
        resp = await self.client.get("/api/version")
        self.assertEqual(resp.status, 200)

    async def test_remote_mode_cancel_endpoint_requires_token(self):
        no_auth = await self.client.post("/api/runs/test-run/cancel")
        self.assertEqual(no_auth.status, 401)

        with_auth = await self.client.post(
            "/api/runs/test-run/cancel",
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(with_auth.status, 200)

    async def test_remote_mode_runs_routes_require_token(self):
        no_auth = await self.client.get("/api/runs")
        self.assertEqual(no_auth.status, 401)

        with_auth = await self.client.get(
            "/api/runs",
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(with_auth.status, 200)

    async def test_remote_mode_setup_bootstrap_requires_token(self):
        no_auth = await self.client.get("/api/setup/bootstrap")
        self.assertEqual(no_auth.status, 401)

        with_auth = await self.client.get(
            "/api/setup/bootstrap",
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(with_auth.status, 200)

    async def test_remote_mode_setup_repair_requires_token(self):
        no_auth = await self.client.post("/api/setup/repair", json={"skip_install": True, "skip_doctor": True})
        self.assertEqual(no_auth.status, 401)

    async def test_remote_mode_audit_routes_require_token(self):
        no_auth = await self.client.get("/api/audit/files")
        self.assertEqual(no_auth.status, 401)

        with_auth = await self.client.get(
            "/api/audit/files",
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertNotEqual(with_auth.status, 401)

    async def test_remote_mode_realtime_ws_requires_token(self):
        with self.assertRaises(WSServerHandshakeError) as ctx:
            await self.client.ws_connect("/api/realtime/ws")
        self.assertEqual(ctx.exception.status, 401)

    async def test_remote_mode_realtime_upload_requires_token(self):
        form = aiohttp.FormData()
        form.add_field("file", b"x", filename="x.txt", content_type="text/plain")
        no_auth = await self.client.post("/api/realtime/upload", data=form)
        self.assertEqual(no_auth.status, 401)


class TestServerAccessModeRemoteVersionLocked(AioHTTPTestCase):
    async def get_application(self):
        cfg = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
            server=ServerConfig(
                access_mode="remote",
                api_token="test-token",
                allow_unauthenticated_version=False,
            ),
        )
        return create_app(cfg)

    async def test_remote_mode_can_lock_version_endpoint(self):
        no_auth = await self.client.get("/api/version")
        self.assertEqual(no_auth.status, 401)

        with_auth = await self.client.get("/api/version", headers={"Authorization": "Bearer test-token"})
        self.assertEqual(with_auth.status, 200)


class TestServerAccessModeRemoteRateLimit(AioHTTPTestCase):
    async def get_application(self):
        cfg = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
            server=ServerConfig(
                access_mode="remote",
                api_token="test-token",
                rate_limit_enabled=True,
                rate_limit_max_requests=2,
                rate_limit_window_seconds=60,
            ),
        )
        return create_app(cfg)

    async def test_remote_mode_rate_limit_enforced(self):
        headers = {"Authorization": "Bearer test-token"}
        first = await self.client.get("/api/models", headers=headers)
        self.assertEqual(first.status, 200)

        second = await self.client.get("/api/models", headers=headers)
        self.assertEqual(second.status, 200)

        third = await self.client.get("/api/models", headers=headers)
        self.assertEqual(third.status, 429)
        self.assertTrue((third.headers.get("Retry-After") or "").strip())


class TestServerAccessModeRemoteRateLimitDisabled(AioHTTPTestCase):
    async def get_application(self):
        cfg = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
            server=ServerConfig(
                access_mode="remote",
                api_token="test-token",
                rate_limit_enabled=False,
                rate_limit_max_requests=1,
                rate_limit_window_seconds=60,
            ),
        )
        return create_app(cfg)

    async def test_remote_mode_rate_limit_can_be_disabled(self):
        headers = {"Authorization": "Bearer test-token"}
        first = await self.client.get("/api/models", headers=headers)
        self.assertEqual(first.status, 200)

        second = await self.client.get("/api/models", headers=headers)
        self.assertEqual(second.status, 200)


if __name__ == "__main__":
    unittest.main()
