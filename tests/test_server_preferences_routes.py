import os
import sqlite3
import tempfile
import unittest

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app


class TestServerPreferencesRoutesLocal(AioHTTPTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._prev_db_path = os.environ.get("THOMAS_DB_PATH")
        self._db_path = f"{self._tmpdir.name}\\prefs_local.sqlite"
        os.environ["THOMAS_DB_PATH"] = self._db_path

    def tearDown(self) -> None:
        if self._prev_db_path is None:
            os.environ.pop("THOMAS_DB_PATH", None)
        else:
            os.environ["THOMAS_DB_PATH"] = self._prev_db_path
        try:
            self._tmpdir.cleanup()
        finally:
            super().tearDown()

    async def get_application(self):
        return create_app(
            AppConfig(
                models={"local": ModelConfig(name="local", model="dummy")},
                default_model="local",
                memory=MemoryConfig(root=self._tmpdir.name),
                server=ServerConfig(access_mode="local"),
            )
        )

    async def test_preferences_defaults_and_partial_patch(self):
        resp = await self.client.get("/api/preferences")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["appearance"]["theme"], "auto")
        self.assertEqual(data["appearance"]["font_size"], 16)
        self.assertEqual(data["memory"]["enabled_global"], True)

        resp = await self.client.patch(
            "/api/preferences",
            json={"appearance": {"theme": "dark", "font_size": 19}},
        )
        self.assertEqual(resp.status, 200)
        updated = await resp.json()
        self.assertEqual(updated["appearance"]["theme"], "dark")
        self.assertEqual(updated["appearance"]["font_size"], 19)
        self.assertEqual(updated["appearance"]["bubble_style"], "rounded")

        resp = await self.client.patch("/api/preferences", json={"appearance": {"bubble_style": "compact"}})
        self.assertEqual(resp.status, 200)
        updated = await resp.json()
        self.assertEqual(updated["appearance"]["theme"], "dark")
        self.assertEqual(updated["appearance"]["font_size"], 19)
        self.assertEqual(updated["appearance"]["bubble_style"], "compact")

    async def test_thread_memory_override_lifecycle(self):
        resp = await self.client.get("/api/preferences?thread_id=t1")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIs(data["memory"]["thread_enabled"], True)

        resp = await self.client.patch("/api/preferences?thread_id=t1", json={"memory": {"thread_enabled": False}})
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIs(data["memory"]["thread_enabled"], False)

        resp = await self.client.get("/api/preferences?thread_id=t2")
        self.assertEqual(resp.status, 200)
        self.assertIs((await resp.json())["memory"]["thread_enabled"], True)

        resp = await self.client.patch("/api/preferences?thread_id=t1", json={"memory": {"thread_enabled": None}})
        self.assertEqual(resp.status, 200)
        self.assertIs((await resp.json())["memory"]["thread_enabled"], True)

    async def test_settings_js_route_is_available(self):
        resp = await self.client.get("/js/settings.js")
        self.assertEqual(resp.status, 200)
        text = await resp.text()
        self.assertIn("/api/preferences", text)

    async def test_api_key_storage_works_via_aiohttp_route(self):
        resp = await self.client.patch("/api/preferences", json={"api_keys": {"openai": "sk-test-123456"}})
        self.assertEqual(resp.status, 200)

        data = await resp.json()
        masked = data["api_keys"]["openai"]
        self.assertIsInstance(masked, str)
        self.assertTrue(masked.endswith("3456"))
        self.assertNotIn("sk-test", masked)

        conn = sqlite3.connect(os.environ["THOMAS_DB_PATH"])
        row = conn.execute(
            "SELECT enc_value, mask_tail, key_hash FROM preference_keys WHERE provider='openai'",
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        enc, mask_tail, key_hash = row
        self.assertIsNotNone(enc)
        self.assertNotIn("sk-test", str(enc))
        self.assertEqual(len(key_hash), 64)


class TestServerPreferencesRoutesRemote(AioHTTPTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._prev_db_path = os.environ.get("THOMAS_DB_PATH")
        self._db_path = f"{self._tmpdir.name}\\prefs_remote.sqlite"
        os.environ["THOMAS_DB_PATH"] = self._db_path

    def tearDown(self) -> None:
        if self._prev_db_path is None:
            os.environ.pop("THOMAS_DB_PATH", None)
        else:
            os.environ["THOMAS_DB_PATH"] = self._prev_db_path
        try:
            self._tmpdir.cleanup()
        finally:
            super().tearDown()

    async def get_application(self):
        return create_app(
            AppConfig(
                models={"local": ModelConfig(name="local", model="dummy")},
                default_model="local",
                memory=MemoryConfig(root=self._tmpdir.name),
                server=ServerConfig(access_mode="remote", api_token="test-token"),
            )
        )

    async def test_preferences_route_requires_auth_in_remote_mode(self):
        resp = await self.client.get("/api/preferences")
        self.assertEqual(resp.status, 401)

        resp = await self.client.patch("/api/preferences", json={"voice": {"tts_voice": "nova"}})
        self.assertEqual(resp.status, 401)

        headers = {"Authorization": "Bearer test-token"}
        resp = await self.client.get("/api/preferences", headers=headers)
        self.assertEqual(resp.status, 200)

        resp = await self.client.patch(
            "/api/preferences",
            headers=headers,
            json={"voice": {"tts_voice": "nova"}},
        )
        self.assertEqual(resp.status, 200)
