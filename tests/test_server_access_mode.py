import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import aiohttp
from aiohttp.client_exceptions import WSServerHandshakeError
from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, ModelConfig, ServerConfig
from thomas.marketplace.observability.run_db import connect, ensure_schema
from thomas.server.app import create_app
from thomas.server.app_middleware_handlers import _is_sandboxed_artifact_asset_request
from thomas.server.app_middleware_security import (
    cors_origin_for_request,
    resource_policy_for_request,
)


class _ArtifactAssetRequest:
    def __init__(self, path: str, *, method: str = "GET", **headers: str) -> None:
        self.path = path
        self.method = method
        self.headers = headers


class TestSandboxedArtifactAssetAccess(unittest.TestCase):
    def test_main_origin_never_relaxes_direct_deliverable_assets(self):
        request = _ArtifactAssetRequest(
            "/deliverable/exec-0123456789ab/src/main.js",
            Origin="null",
            **{
                "Sec-Fetch-Site": "cross-site",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Dest": "script",
            },
        )
        self.assertEqual(resource_policy_for_request(request), "same-site")
        self.assertIsNone(cors_origin_for_request(request))

    def test_missing_fetch_metadata_keeps_strict_main_origin_policy(self):
        request = _ArtifactAssetRequest("/deliverable/exec-0123456789ab/styles.css")
        self.assertEqual(resource_policy_for_request(request), "same-site")
        self.assertIsNone(cors_origin_for_request(request))

    def test_allows_only_passive_no_cors_generated_app_assets(self):
        request = _ArtifactAssetRequest(
            "/api/evolve/agent/artifact-content/" + ("a" * 64) + "/fc_123/game.js",
            **{
                "Sec-Fetch-Site": "cross-site",
                "Sec-Fetch-Mode": "no-cors",
                "Sec-Fetch-Dest": "script",
            },
        )
        self.assertTrue(_is_sandboxed_artifact_asset_request(request))

        missing_capability = _ArtifactAssetRequest(
            "/api/evolve/agent/artifact/fc_123/game.js",
            **{
                "Sec-Fetch-Site": "cross-site",
                "Sec-Fetch-Mode": "no-cors",
                "Sec-Fetch-Dest": "script",
            },
        )
        self.assertFalse(_is_sandboxed_artifact_asset_request(missing_capability))

    def test_code_artifact_capability_allows_module_font_and_data_cors(self):
        prefix = "/api/evolve/agent/artifact-content/" + ("c" * 64) + "/fc_123/"
        base = {
            "Origin": "null",
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-Mode": "cors",
        }
        for tail, destination in (
            ("src/main.js", "script"),
            ("fonts/app.woff2", "font"),
            ("data.json", "empty"),
        ):
            request = _ArtifactAssetRequest(prefix + tail, **{**base, "Sec-Fetch-Dest": destination})
            with self.subTest(tail=tail, destination=destination):
                self.assertTrue(_is_sandboxed_artifact_asset_request(request))
                self.assertEqual(resource_policy_for_request(request), "cross-origin")
                self.assertEqual(cors_origin_for_request(request), "null")

    def test_rejects_cross_site_documents_api_fetches_and_mutations(self):
        base = {
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Dest": "document",
        }
        self.assertFalse(
            _is_sandboxed_artifact_asset_request(
                _ArtifactAssetRequest("/api/evolve/agent/artifact/fc_123/index.html", **base)
            )
        )
        self.assertFalse(
            _is_sandboxed_artifact_asset_request(
                _ArtifactAssetRequest(
                    "/api/models",
                    **{
                        "Sec-Fetch-Site": "cross-site",
                        "Sec-Fetch-Mode": "no-cors",
                        "Sec-Fetch-Dest": "script",
                    },
                )
            )
        )
        self.assertFalse(
            _is_sandboxed_artifact_asset_request(
                _ArtifactAssetRequest(
                    "/api/evolve/agent/artifact-content/" + ("b" * 64) + "/fc_123/app.js",
                    method="POST",
                    **{
                        "Sec-Fetch-Site": "cross-site",
                        "Sec-Fetch-Mode": "no-cors",
                        "Sec-Fetch-Dest": "script",
                    },
                )
            )
        )
        self.assertFalse(
            _is_sandboxed_artifact_asset_request(
                _ArtifactAssetRequest(
                    "/api/evolve/agent/artifact-content/" + ("b" * 64) + "/fc_123/app.js",
                    Origin="https://evil.example",
                    **{
                        "Sec-Fetch-Site": "cross-site",
                        "Sec-Fetch-Mode": "no-cors",
                        "Sec-Fetch-Dest": "script",
                    },
                )
            )
        )


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

    async def test_local_mode_workspace_routes_are_available(self):
        resp = await self.client.get("/api/workspaces")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIsInstance(data, list)

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

    async def test_setup_diagnostics_endpoint_returns_validator_snapshot(self):
        resp = await self.client.get("/api/setup/diagnostics")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("config", data)
        self.assertIn("runtime", data)
        self.assertIn("next_actions", data)
        self.assertIn("summary", data["config"])

    async def test_onboarding_outcomes_endpoint_returns_summary(self):
        resp = await self.client.get("/api/onboarding/outcomes")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("summary", data)
        self.assertIn("window_days", data)

    async def test_onboarding_outcomes_gate_endpoint_returns_gate_payload(self):
        resp = await self.client.get("/api/onboarding/outcomes/gate")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("gate", data)
        self.assertIn("onboarding_summary", data)
        self.assertIn("ok", data)

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

    async def test_onboarding_telemetry_accepts_elapsed_ms_and_session_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "runs.sqlite3"
            with patch.dict(os.environ, {"THOMAS_RUNS_DB_PATH": str(db)}):
                resp = await self.client.post(
                    "/api/onboarding/telemetry",
                    json={
                        "event": "wizard.opened",
                        "payload": {
                            "onboarding_session_id": "session-123",
                            "elapsed_ms": 3210,
                            "step": "choose_path",
                        },
                    },
                )
                self.assertEqual(resp.status, 200)
                ensure_schema(db)
                con = connect(db)
                try:
                    row = con.execute(
                        "SELECT run_id, t_ms, payload_json FROM events ORDER BY id DESC LIMIT 1"
                    ).fetchone()
                finally:
                    con.close()

        self.assertIsNotNone(row)
        self.assertEqual(int(row["t_ms"]), 3210)
        self.assertIn("session-123", str(row["run_id"]))
        payload = json.loads(str(row["payload_json"] or "{}"))
        self.assertEqual(payload.get("onboarding_session_id"), "session-123")
        self.assertEqual(payload.get("elapsed_ms"), 3210)

    async def test_default_security_headers_are_set(self):
        resp = await self.client.get("/")
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(resp.headers.get("Referrer-Policy"), "strict-origin-when-cross-origin")
        self.assertEqual(resp.headers.get("X-Frame-Options"), "SAMEORIGIN")
        self.assertIn("default-src 'self'", str(resp.headers.get("Content-Security-Policy") or ""))
        self.assertIn(
            "frame-src 'self' http://127.0.0.1:*",
            str(resp.headers.get("Content-Security-Policy") or ""),
        )
        self.assertEqual(resp.headers.get("Cross-Origin-Opener-Policy"), "same-origin")
        self.assertEqual(resp.headers.get("Cross-Origin-Resource-Policy"), "same-site")
        self.assertEqual(resp.headers.get("X-Permitted-Cross-Domain-Policies"), "none")

    async def test_local_mode_blocks_cross_site_mutating_browser_requests(self):
        resp = await self.client.post(
            "/api/session/new",
            headers={
                "Origin": "https://evil.example",
                "Sec-Fetch-Site": "cross-site",
            },
            json={},
        )
        self.assertEqual(resp.status, 403)

    async def test_local_mode_allows_same_origin_mutating_browser_requests(self):
        origin = str(self.client.make_url("/")).rstrip("/")
        resp = await self.client.post(
            "/api/session/new",
            headers={
                "Origin": origin,
                "Sec-Fetch-Site": "same-origin",
            },
            json={},
        )
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

    async def test_remote_mode_workspace_routes_require_token(self):
        no_auth = await self.client.get("/api/workspaces")
        self.assertEqual(no_auth.status, 401)

        with_auth = await self.client.get(
            "/api/workspaces",
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(with_auth.status, 200)

    async def test_remote_mode_chat_v2_read_routes_require_token(self):
        paths = [
            "/api/v2/chat/session/private-session",
            "/api/v2/chat/session/private-session/export",
            "/api/v2/chat/session/private-session/delegations",
            "/api/v2/chat/voice/status",
            "/api/v2/chat/specialists",
        ]
        for path in paths:
            no_auth = await self.client.get(path)
            self.assertEqual(no_auth.status, 401, path)

        expected_authenticated = [404, 404, 200, 200, 200]
        for path, expected_status in zip(paths, expected_authenticated, strict=True):
            with_auth = await self.client.get(
                path,
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(with_auth.status, expected_status, path)

    async def test_remote_mode_deliverables_require_token(self):
        path = "/deliverable/private-session/secret.pdf?download=1"
        no_auth = await self.client.get(path)
        self.assertEqual(no_auth.status, 401)

        with_auth = await self.client.get(
            path,
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(with_auth.status, 404)

    async def test_remote_mode_workspace_mutation_requires_token(self):
        no_auth = await self.client.post("/api/workspaces", json={"name": "remote-ws"})
        self.assertEqual(no_auth.status, 401)

        with_auth = await self.client.post(
            "/api/workspaces",
            headers={"Authorization": "Bearer test-token"},
            json={"name": "remote-ws"},
        )
        self.assertEqual(with_auth.status, 201)
        data = await with_auth.json()
        self.assertIn("workspace_id", data)

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

    async def test_remote_mode_setup_diagnostics_requires_token(self):
        no_auth = await self.client.get("/api/setup/diagnostics")
        self.assertEqual(no_auth.status, 401)

        with_auth = await self.client.get(
            "/api/setup/diagnostics",
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(with_auth.status, 200)

    async def test_remote_mode_setup_diagnostics_flags_webhook_signature_downgrade(self):
        with patch.dict(
            os.environ,
            {
                "THOMAS_WEBHOOK_REQUIRE_SIGNATURES": "0",
                "THOMAS_GITHUB_WEBHOOK_SECRET": "",
                "THOMAS_GITHUB_WEBHOOK_SECRETS": "",
                "THOMAS_STRIPE_WEBHOOK_SECRET": "",
                "THOMAS_STRIPE_WEBHOOK_SECRETS": "",
            },
            clear=False,
        ):
            resp = await self.client.get(
                "/api/setup/diagnostics",
                headers={"Authorization": "Bearer test-token"},
            )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        codes = {str(item.get("code") or "") for item in list(data.get("config", {}).get("errors") or [])}
        self.assertIn("server.remote.webhook_signatures_disabled", codes)
        next_actions = [str(item or "") for item in list(data.get("next_actions") or [])]
        self.assertTrue(any("webhook signature enforcement" in item.lower() for item in next_actions))

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

    async def test_remote_mode_onboarding_telemetry_requires_token(self):
        no_auth = await self.client.post("/api/onboarding/telemetry", json={"event": "wizard.progress"})
        self.assertEqual(no_auth.status, 401)

        with_auth = await self.client.post(
            "/api/onboarding/telemetry",
            headers={"Authorization": "Bearer test-token"},
            json={"event": "wizard.progress", "payload": {"step": "deps"}},
        )
        self.assertEqual(with_auth.status, 200)
        data = await with_auth.json()
        self.assertTrue(bool(data.get("ok")))

    async def test_remote_mode_onboarding_outcomes_requires_token(self):
        no_auth = await self.client.get("/api/onboarding/outcomes")
        self.assertEqual(no_auth.status, 401)

        with_auth = await self.client.get(
            "/api/onboarding/outcomes",
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(with_auth.status, 200)

    async def test_remote_mode_onboarding_outcomes_gate_requires_token(self):
        no_auth = await self.client.get("/api/onboarding/outcomes/gate")
        self.assertEqual(no_auth.status, 401)

        with_auth = await self.client.get(
            "/api/onboarding/outcomes/gate",
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(with_auth.status, 200)

    async def test_remote_mode_defaults_webhook_signature_enforcement_on(self):
        with patch.dict(
            os.environ,
            {
                "THOMAS_WEBHOOK_REQUIRE_SIGNATURES": "",
                "THOMAS_GITHUB_WEBHOOK_SECRET": "",
                "THOMAS_GITHUB_WEBHOOK_SECRETS": "",
                "THOMAS_ENV": "",
                "ENV": "",
                "PYTHON_ENV": "",
            },
            clear=False,
        ):
            resp = await self.client.post(
                "/webhooks/receive/github",
                data=b"{}",
                headers={
                    "content-type": "application/json",
                    "X-GitHub-Event": "push",
                },
            )
        self.assertEqual(resp.status, 503)
        data = await resp.json()
        self.assertIn("signature enforcement is enabled", str(data.get("detail") or ""))


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
