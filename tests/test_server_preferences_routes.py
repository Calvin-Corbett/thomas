import os
import sqlite3
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase

import thomas.core.rules_of_road as rules_of_road
from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig

if not hasattr(rules_of_road, "build_remediation_prompt"):
    rules_of_road.build_remediation_prompt = lambda *args, **kwargs: ""
if not hasattr(rules_of_road, "evaluate_rules"):
    rules_of_road.evaluate_rules = lambda *args, **kwargs: {}

from thomas.server.app import create_app
from thomas.server.app_keys import APP_LOCAL_STEP_UP_AUTH_PROVIDER


class _AllowAuthProvider:
    def authorize(self, action: str, reason: str):
        _ = (action, reason)

        class _Result:
            authorized = True
            method = "test"
            platform = "windows"
            error_code = None

        return _Result()


class _DenyAuthProvider:
    def authorize(self, action: str, reason: str):
        _ = (action, reason)

        class _Result:
            authorized = False
            method = "test"
            platform = "windows"
            error_code = "auth_denied"

        return _Result()


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

    async def test_profile_type_patch_roundtrip(self):
        resp = await self.client.patch("/api/preferences", json={"profile": {"profile_type": "non_coder"}})
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(str((data.get("profile") or {}).get("profile_type") or ""), "non_coder")

    async def test_profile_review_depth_patch_roundtrip(self):
        resp = await self.client.patch("/api/preferences", json={"profile": {"review_depth": "simplified"}})
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(str((data.get("profile") or {}).get("review_depth") or ""), "simple")

    async def test_security_defaults_exposed_in_preferences(self):
        resp = await self.client.get("/api/preferences")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        security = (data.get("advanced") or {}).get("security") or {}
        tools = (data.get("advanced") or {}).get("tools") or {}
        self.assertIs(bool(security.get("allow_third_party_agent_access", False)), True)
        self.assertIs(bool(security.get("human_breakglass_enabled", True)), False)
        self.assertEqual(str(security.get("guardrails_posture") or ""), "standard")
        self.assertEqual(str(security.get("enforcement_mode") or ""), "protected")
        self.assertTrue(bool(tools.get("require_command_approval", False)))

    async def test_generic_preferences_patch_cannot_change_advanced_security(self):
        resp = await self.client.patch(
            "/api/preferences",
            json={"advanced": {"security": {"allow_third_party_agent_access": False}}},
        )
        self.assertEqual(resp.status, 400)
        self.assertIn("dedicated /api/security/* routes", await resp.text())

    async def test_generic_preferences_patch_blocks_guardrail_weakening(self):
        resp = await self.client.patch(
            "/api/preferences",
            json={"advanced": {"tools": {"require_command_approval": False}}},
        )
        self.assertEqual(resp.status, 400)
        self.assertIn("/api/security/guardrails-posture", await resp.text())

    async def test_guardrails_posture_strengthening_does_not_require_auth(self):
        resp = await self.client.post(
            "/api/security/guardrails-posture",
            json={"posture": "locked"},
        )
        self.assertEqual(resp.status, 200)
        payload = await resp.json()
        self.assertTrue(bool(payload.get("ok")))
        self.assertEqual(str(payload.get("posture") or ""), "locked")
        self.assertFalse(bool(payload.get("auth_verified", True)))

        prefs_resp = await self.client.get("/api/preferences")
        prefs = await prefs_resp.json()
        security = (prefs.get("advanced") or {}).get("security") or {}
        tools = (prefs.get("advanced") or {}).get("tools") or {}
        self.assertEqual(str(security.get("guardrails_posture") or ""), "locked")
        self.assertFalse(bool(tools.get("allow_shell", True)))

    async def test_guardrails_posture_weakening_requires_auth(self):
        resp = await self.client.post(
            "/api/security/guardrails-posture",
            json={"posture": "builder"},
        )
        self.assertEqual(resp.status, 503)
        payload = await resp.json()
        self.assertFalse(bool(payload.get("ok", True)))
        self.assertEqual(str(payload.get("reason") or ""), "local_step_up_auth_unavailable")

        self.app[APP_LOCAL_STEP_UP_AUTH_PROVIDER] = _AllowAuthProvider()
        allowed = await self.client.post(
            "/api/security/guardrails-posture",
            json={"posture": "builder"},
        )
        self.assertEqual(allowed.status, 200)
        allowed_payload = await allowed.json()
        self.assertTrue(bool(allowed_payload.get("ok")))
        self.assertEqual(str(allowed_payload.get("posture") or ""), "builder")
        self.assertTrue(bool(allowed_payload.get("auth_verified", False)))

    async def test_dedicated_toggle_route_updates_security_pref_and_live_health(self):
        self.app[APP_LOCAL_STEP_UP_AUTH_PROVIDER] = _AllowAuthProvider()
        resp = await self.client.post(
            "/api/security/third-party-agent-access",
            json={"enabled": False},
        )
        self.assertEqual(resp.status, 200)
        payload = await resp.json()
        self.assertTrue(bool(payload.get("ok")))
        self.assertFalse(bool(payload.get("enabled", True)))
        self.assertEqual(str(payload.get("enforcement_mode") or ""), "protected")
        self.assertTrue(bool(payload.get("auth_verified", False)))

        prefs_resp = await self.client.get("/api/preferences")
        prefs = await prefs_resp.json()
        security = (prefs.get("advanced") or {}).get("security") or {}
        self.assertFalse(bool(security.get("allow_third_party_agent_access", True)))
        self.assertEqual(str(security.get("enforcement_mode") or ""), "protected")
        self.assertTrue(bool(security.get("last_changed_at")))
        self.assertTrue(bool(security.get("last_changed_by")))

        health_resp = await self.client.get("/api/health")
        health = await health_resp.json()
        self.assertTrue(bool((health.get("security") or {}).get("protected_mode", False)))

    async def test_dedicated_toggle_route_denies_when_local_auth_fails(self):
        self.app[APP_LOCAL_STEP_UP_AUTH_PROVIDER] = _DenyAuthProvider()
        resp = await self.client.post(
            "/api/security/third-party-agent-access",
            json={"enabled": False},
        )
        self.assertEqual(resp.status, 403)
        payload = await resp.json()
        self.assertFalse(bool(payload.get("ok", True)))
        self.assertFalse(bool(payload.get("auth_verified", True)))
        self.assertEqual(str(payload.get("reason") or ""), "auth_denied")

        prefs_resp = await self.client.get("/api/preferences")
        prefs = await prefs_resp.json()
        security = (prefs.get("advanced") or {}).get("security") or {}
        self.assertTrue(bool(security.get("allow_third_party_agent_access", False)))

    async def test_breakglass_opt_in_route_updates_security_pref(self):
        with (
            patch(
                "thomas.server.routes.third_party_agent_access_aiohttp.authorize_breakglass_toggle",
                return_value=SimpleNamespace(
                    ok=True,
                    message="approved",
                    actor="WORKSTATION\\operator",
                    method="windows-credential-dialog",
                    cancelled=False,
                    receipt="receipt-123",
                ),
            ),
            patch(
                "scripts.breakglass_auth.consume_breakglass_toggle_receipt",
                return_value=SimpleNamespace(actor="WORKSTATION\\operator", method="windows-credential-dialog"),
            ),
        ):
            resp = await self.client.post(
                "/api/security/breakglass-opt-in",
                json={"enabled": True},
            )
        self.assertEqual(resp.status, 200)
        payload = await resp.json()
        self.assertTrue(bool(payload.get("ok")))
        self.assertTrue(bool(payload.get("enabled", False)))
        self.assertTrue(bool(payload.get("auth_verified", False)))
        security_payload = payload.get("security") or {}
        self.assertTrue(bool(security_payload.get("human_breakglass_enabled", False)))

        prefs_resp = await self.client.get("/api/preferences")
        prefs = await prefs_resp.json()
        security = (prefs.get("advanced") or {}).get("security") or {}
        self.assertTrue(bool(security.get("human_breakglass_enabled", False)))
        self.assertTrue(bool(security.get("human_breakglass_changed_at")))
        self.assertEqual(str(security.get("human_breakglass_changed_by") or ""), "WORKSTATION\\operator")

    async def test_breakglass_opt_in_route_denies_when_local_auth_fails(self):
        with patch(
            "thomas.server.routes.third_party_agent_access_aiohttp.authorize_breakglass_toggle",
            return_value=SimpleNamespace(
                ok=False,
                message="denied",
                actor="WORKSTATION\\operator",
                method="windows-credential-dialog",
                cancelled=False,
                receipt=None,
            ),
        ):
            resp = await self.client.post(
                "/api/security/breakglass-opt-in",
                json={"enabled": True},
            )
        self.assertEqual(resp.status, 403)
        payload = await resp.json()
        self.assertFalse(bool(payload.get("ok", True)))
        self.assertFalse(bool(payload.get("auth_verified", True)))
        self.assertEqual(str(payload.get("reason") or ""), "auth_denied")

        prefs_resp = await self.client.get("/api/preferences")
        prefs = await prefs_resp.json()
        security = (prefs.get("advanced") or {}).get("security") or {}
        self.assertFalse(bool(security.get("human_breakglass_enabled", True)))


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
