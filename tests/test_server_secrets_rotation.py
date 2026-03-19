from __future__ import annotations

import os
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app
from thomas.server.secrets import SecretStore


def _iso_to_utc(text: str):
    raw = str(text or "").strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    from datetime import datetime, timezone

    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class TestSecretStoreRotation(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_rotation_metadata_persists_and_status_transitions(self) -> None:
        root = Path(self._tmpdir.name)
        store = SecretStore(root)
        store.set("local", "secret-key", persist=True, rotation_days=30)
        meta = store.metadata("local")
        self.assertEqual(int(meta.get("rotation_days") or 0), 30)
        updated_at = _iso_to_utc(str(meta.get("updated_at") or ""))

        due_soon_rows = store.rotation_reminders(now_utc=updated_at + timedelta(days=28), warning_days=3)
        due_soon = next((row for row in due_soon_rows if str(row.get("profile")) == "local"), None)
        self.assertIsNotNone(due_soon)
        self.assertEqual(str((due_soon or {}).get("status")), "due_soon")

        expired_rows = store.rotation_reminders(now_utc=updated_at + timedelta(days=33), warning_days=3)
        expired = next((row for row in expired_rows if str(row.get("profile")) == "local"), None)
        self.assertIsNotNone(expired)
        self.assertEqual(str((expired or {}).get("status")), "expired")

        reloaded = SecretStore(root)
        reloaded_meta = reloaded.metadata("local")
        self.assertEqual(int(reloaded_meta.get("rotation_days") or 0), 30)


class TestSecretsRotationApi(AioHTTPTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._prev_db_path = os.environ.get("THOMAS_DB_PATH")
        os.environ["THOMAS_DB_PATH"] = os.path.join(self._tmpdir.name, "prefs_secrets.sqlite")

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
        cfg = AppConfig(
            models={
                "local": ModelConfig(
                    name="local",
                    provider="openai_compat",
                    model="dummy",
                    base_url="http://127.0.0.1:11434/v1",
                )
            },
            default_model="local",
            memory=MemoryConfig(root=self._tmpdir.name),
            server=ServerConfig(access_mode="local"),
        )
        return create_app(cfg)

    async def test_secret_set_accepts_rotation_days_and_exposes_metadata(self):
        set_resp = await self.client.post(
            "/api/secrets/local",
            json={"api_key": "sk-local", "persist": False, "rotation_days": 45},
        )
        self.assertEqual(set_resp.status, 200)
        set_body = await set_resp.json()
        self.assertEqual(int(set_body.get("rotation_days") or 0), 45)
        self.assertTrue(str(set_body.get("updated_at") or "").strip())

        list_resp = await self.client.get("/api/secrets")
        self.assertEqual(list_resp.status, 200)
        list_body = await list_resp.json()
        profiles = list_body.get("profiles") or []
        row = next((item for item in profiles if str(item.get("name")) == "local"), {})
        self.assertEqual(int(row.get("rotation_days") or 0), 45)
        self.assertEqual(str(row.get("rotation_days_source") or ""), "profile")
        self.assertEqual(str(row.get("rotation_status") or ""), "ok")

    async def test_secrets_reminders_endpoint(self):
        set_resp = await self.client.post(
            "/api/secrets/local",
            json={"api_key": "sk-local", "persist": False, "rotation_days": 45},
        )
        self.assertEqual(set_resp.status, 200)

        reminders_resp = await self.client.get("/api/secrets/reminders?default_rotation_days=90&warning_days=14")
        self.assertEqual(reminders_resp.status, 200)
        body = await reminders_resp.json()
        self.assertTrue(body.get("ok"))
        self.assertGreaterEqual(int(body.get("count") or 0), 1)
        reminders = body.get("reminders") or []
        row = next((item for item in reminders if str(item.get("profile")) == "local"), {})
        self.assertEqual(int(row.get("rotation_days") or 0), 45)

    async def test_secret_set_parses_false_string_persist(self):
        resp = await self.client.post(
            "/api/secrets/local",
            json={"api_key": "sk-local", "persist": "false", "rotation_days": 45},
        )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertFalse(bool(body.get("persisted")))

        list_resp = await self.client.get("/api/secrets")
        self.assertEqual(list_resp.status, 200)
        profiles = (await list_resp.json()).get("profiles") or []
        row = next((item for item in profiles if str(item.get("name")) == "local"), {})
        self.assertFalse(bool(row.get("persisted")))

    async def test_secret_set_rejects_non_object_json(self):
        resp = await self.client.post("/api/secrets/local", json=["bad"])
        self.assertEqual(resp.status, 400)

    async def test_secret_set_rejects_invalid_rotation_days(self):
        resp = await self.client.post(
            "/api/secrets/local",
            json={"api_key": "sk-local", "persist": False, "rotation_days": "abc"},
        )
        self.assertEqual(resp.status, 400)
        text = await resp.text()
        self.assertIn("rotation_days must be an integer", text)


if __name__ == "__main__":
    unittest.main()
