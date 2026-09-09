import unittest

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app


class TestServerHealthRoutesLocal(AioHTTPTestCase):
    async def get_application(self):
        cfg = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
            server=ServerConfig(access_mode="local"),
        )
        return create_app(cfg)

    async def test_healthz_alias_matches_api_health_shape(self):
        api_resp = await self.client.get("/api/health")
        self.assertEqual(api_resp.status, 200)
        api_payload = await api_resp.json()

        healthz_resp = await self.client.get("/healthz")
        self.assertEqual(healthz_resp.status, 200)
        healthz_payload = await healthz_resp.json()

        for payload in (api_payload, healthz_payload):
            self.assertIn("status", payload)
            self.assertIn("uptime_s", payload)
            self.assertIn("features", payload)
            self.assertIn("crash_count", payload)


class TestServerHealthRoutesRemote(AioHTTPTestCase):
    async def get_application(self):
        cfg = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
            server=ServerConfig(access_mode="remote", api_token="test-token"),
        )
        return create_app(cfg)

    async def test_healthz_is_public_for_liveness_checks(self):
        resp = await self.client.get("/healthz")
        self.assertEqual(resp.status, 200)
        payload = await resp.json()
        self.assertIn("status", payload)


if __name__ == "__main__":
    unittest.main()
