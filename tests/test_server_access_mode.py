import unittest

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
