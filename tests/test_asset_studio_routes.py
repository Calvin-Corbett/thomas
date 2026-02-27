import asyncio
import json
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app


class TestAssetStudioRoutes(AioHTTPTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._prev_db_path = os.environ.get("THOMAS_DB_PATH")
        self._db_path = os.path.join(self._tmpdir.name, "prefs_asset_studio.sqlite")
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
        cfg = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
            memory=MemoryConfig(root=self._tmpdir.name),
            server=ServerConfig(access_mode="local"),
        )
        return create_app(cfg)

    async def test_connectors_list_available(self):
        resp = await self.client.get("/api/asset-studio/v1/connectors")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertTrue(body.get("ok"))
        connectors = body.get("connectors") or []
        ids = {str(item.get("id")) for item in connectors if isinstance(item, dict)}
        self.assertIn("ffmpeg", ids)
        self.assertIn("blender", ids)
        self.assertIn("unreal", ids)
        self.assertIn("unity", ids)
        self.assertIn("godot", ids)
        self.assertIn("github", ids)
        self.assertIn("notion", ids)
        self.assertIn("figma", ids)
        self.assertIn("comfyui", ids)
        self.assertIn("opentimelineio", ids)

    async def test_detect_unknown_connector_404(self):
        resp = await self.client.post("/api/asset-studio/v1/connectors/not-a-connector/detect", json={})
        self.assertEqual(resp.status, 404)

    async def test_connector_actions_endpoint_returns_action_contract(self):
        resp = await self.client.get("/api/asset-studio/v1/connectors/ffmpeg/actions")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertTrue(body.get("ok"))
        self.assertEqual(str(body.get("connector_id") or ""), "ffmpeg")
        actions = body.get("actions") or []
        self.assertGreaterEqual(len(actions), 1)
        ids = {str(item.get("id") or "") for item in actions if isinstance(item, dict)}
        self.assertIn("transcode", ids)

    async def test_health_endpoint_returns_summary(self):
        resp = await self.client.get("/api/asset-studio/v1/health")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertTrue(body.get("ok"))
        health = body.get("health") or {}
        connectors = health.get("connectors") or {}
        runtime = health.get("runtime") or {}
        self.assertGreaterEqual(int(connectors.get("total") or 0), 1)
        self.assertGreaterEqual(int(runtime.get("active_tasks") or 0), 0)
        self.assertIn("store_path", health)

    async def test_comfy_status_endpoint_uses_service(self):
        from thomas.server.routes.asset_studio_aiohttp import APP_ASSET_STUDIO_COMFY_SERVICE

        service = self.app[APP_ASSET_STUDIO_COMFY_SERVICE]
        with patch.object(
            service,
            "status",
            new=AsyncMock(return_value={"server_url": "http://127.0.0.1:8188", "running": False}),
        ):
            resp = await self.client.get("/api/asset-studio/v1/comfy/status")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertTrue(body.get("ok"))
        status = body.get("status") or {}
        self.assertEqual(str(status.get("server_url") or ""), "http://127.0.0.1:8188")
        self.assertFalse(bool(status.get("running")))

    async def test_comfy_queue_endpoint_uses_service(self):
        from thomas.server.routes.asset_studio_aiohttp import APP_ASSET_STUDIO_COMFY_SERVICE

        service = self.app[APP_ASSET_STUDIO_COMFY_SERVICE]
        with patch.object(
            service,
            "queue_prompt",
            new=AsyncMock(return_value={"ok": True, "prompt_id": "pid-123"}),
        ):
            resp = await self.client.post(
                "/api/asset-studio/v1/comfy/queue",
                json={"workflow_json": '{"3": {"inputs": {}}}'},
            )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertTrue(body.get("ok"))
        result = body.get("result") or {}
        self.assertEqual(str(result.get("prompt_id") or ""), "pid-123")

    async def test_completion_webhook_config_crud(self):
        first_get = await self.client.get("/api/asset-studio/v1/webhooks/completion")
        self.assertEqual(first_get.status, 200)
        first_body = await first_get.json()
        self.assertTrue(first_body.get("ok"))
        self.assertFalse(bool(first_body.get("configured")))
        self.assertIsNone(first_body.get("webhook"))

        create = await self.client.post(
            "/api/asset-studio/v1/webhooks/completion",
            json={
                "url": "https://example.test/hooks/thomas",
                "secret": "topsecret",
                "enabled": True,
                "timeout_s": 4,
            },
        )
        self.assertEqual(create.status, 200)
        create_body = await create.json()
        self.assertTrue(create_body.get("ok"))
        webhook = create_body.get("webhook") or {}
        self.assertEqual(str(webhook.get("url") or ""), "https://example.test/hooks/thomas")
        self.assertTrue(bool(webhook.get("has_secret")))
        self.assertTrue(bool(webhook.get("enabled")))
        self.assertEqual(int(webhook.get("timeout_s") or 0), 4)

        second_get = await self.client.get("/api/asset-studio/v1/webhooks/completion")
        self.assertEqual(second_get.status, 200)
        second_body = await second_get.json()
        self.assertTrue(second_body.get("configured"))

        delete = await self.client.delete("/api/asset-studio/v1/webhooks/completion")
        self.assertEqual(delete.status, 200)
        delete_body = await delete.json()
        self.assertTrue(delete_body.get("ok"))
        self.assertTrue(bool(delete_body.get("deleted")))

        third_get = await self.client.get("/api/asset-studio/v1/webhooks/completion")
        self.assertEqual(third_get.status, 200)
        third_body = await third_get.json()
        self.assertFalse(bool(third_body.get("configured")))
        self.assertIsNone(third_body.get("webhook"))

    async def test_completion_webhook_delivery_records_event(self):
        cfg = await self.client.post(
            "/api/asset-studio/v1/webhooks/completion",
            json={
                "url": "https://example.test/hooks/thomas",
                "secret": "topsecret",
                "enabled": True,
                "timeout_s": 5,
            },
        )
        self.assertEqual(cfg.status, 200)
        captured: list[dict[str, object]] = []

        class _FakeWebhookResponse:
            status = 202

            def read(self, _n: int | None = None) -> bytes:
                return b"accepted"

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb) -> bool:
                return False

            def getcode(self) -> int:
                return int(self.status)

        def _fake_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
            headers = {str(k).lower(): str(v) for k, v in request.header_items()}
            raw = bytes(request.data or b"")
            body = json.loads(raw.decode("utf-8")) if raw else {}
            captured.append(
                {
                    "url": str(getattr(request, "full_url", "")),
                    "headers": headers,
                    "body": body,
                    "timeout": int(timeout or 0),
                }
            )
            return _FakeWebhookResponse()

        with patch("thomas.asset_studio.runtime.urllib.request.urlopen", side_effect=_fake_urlopen):
            create = await self.client.post(
                "/api/asset-studio/v1/jobs",
                json={
                    "connector_id": "ffmpeg",
                    "action_id": "version_check",
                    "payload": {"timeout_s": 20},
                },
            )
            self.assertEqual(create.status, 200)
            job_id = str(((await create.json()).get("job") or {}).get("job_id") or "")
            self.assertTrue(job_id)

            observed_kinds: set[str] = set()
            for _ in range(60):
                events_resp = await self.client.get(f"/api/asset-studio/v1/jobs/{job_id}/events")
                self.assertEqual(events_resp.status, 200)
                events_body = await events_resp.json()
                events = events_body.get("events") or []
                observed_kinds = {str(item.get("kind") or "") for item in events if isinstance(item, dict)}
                if "webhook_ok" in observed_kinds:
                    break
                await asyncio.sleep(0.1)

            self.assertIn("webhook_ok", observed_kinds)
            self.assertGreaterEqual(len(captured), 1)
            outbound = captured[0]
            self.assertEqual(str(outbound.get("url") or ""), "https://example.test/hooks/thomas")
            headers = outbound.get("headers") if isinstance(outbound.get("headers"), dict) else {}
            self.assertEqual(str(headers.get("x-thomas-event") or ""), "asset_studio.job.completed")
            self.assertTrue(str(headers.get("x-thomas-signature") or "").startswith("sha256="))
            body = outbound.get("body") if isinstance(outbound.get("body"), dict) else {}
            self.assertEqual(str(body.get("event") or ""), "asset_studio.job.completed")
            job = body.get("job") if isinstance(body.get("job"), dict) else {}
            self.assertEqual(str(job.get("job_id") or ""), job_id)

    async def test_completion_webhook_retries_then_succeeds(self):
        cfg = await self.client.post(
            "/api/asset-studio/v1/webhooks/completion",
            json={
                "url": "https://example.test/hooks/thomas",
                "secret": "topsecret",
                "enabled": True,
                "timeout_s": 5,
            },
        )
        self.assertEqual(cfg.status, 200)
        attempts = {"count": 0}

        class _FakeWebhookResponse:
            status = 200

            def read(self, _n: int | None = None) -> bytes:
                return b"ok"

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb) -> bool:
                return False

            def getcode(self) -> int:
                return int(self.status)

        def _flaky_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
            _ = request
            _ = timeout
            attempts["count"] = int(attempts.get("count") or 0) + 1
            if attempts["count"] < 3:
                raise RuntimeError("temporary webhook failure")
            return _FakeWebhookResponse()

        with patch("thomas.asset_studio.runtime.urllib.request.urlopen", side_effect=_flaky_urlopen):
            create = await self.client.post(
                "/api/asset-studio/v1/jobs",
                json={
                    "connector_id": "ffmpeg",
                    "action_id": "version_check",
                    "payload": {"timeout_s": 20},
                },
            )
            self.assertEqual(create.status, 200)
            job_id = str(((await create.json()).get("job") or {}).get("job_id") or "")
            self.assertTrue(job_id)

            observed_kinds: set[str] = set()
            for _ in range(90):
                events_resp = await self.client.get(f"/api/asset-studio/v1/jobs/{job_id}/events")
                self.assertEqual(events_resp.status, 200)
                events_body = await events_resp.json()
                events = events_body.get("events") or []
                observed_kinds = {str(item.get("kind") or "") for item in events if isinstance(item, dict)}
                if "webhook_ok" in observed_kinds:
                    break
                await asyncio.sleep(0.1)

            self.assertIn("webhook_retry", observed_kinds)
            self.assertIn("webhook_ok", observed_kinds)
            self.assertEqual(int(attempts.get("count") or 0), 3)

    async def test_job_preview_endpoint_returns_command(self):
        resp = await self.client.post(
            "/api/asset-studio/v1/jobs/preview",
            json={
                "connector_id": "notion",
                "action_id": "sync_page",
                "payload": {"page_id": "abc123"},
            },
        )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertTrue(body.get("ok"))
        preview = body.get("preview") or {}
        self.assertEqual(str(preview.get("connector_id") or ""), "notion")
        self.assertEqual(str(preview.get("action_id") or ""), "sync_page")
        command = preview.get("command") or []
        self.assertGreaterEqual(len(command), 3)
        joined = " ".join(str(part) for part in command)
        self.assertIn("connector_shims", joined)

    async def test_job_validate_endpoint_returns_missing_fields(self):
        resp = await self.client.post(
            "/api/asset-studio/v1/jobs/validate",
            json={
                "connector_id": "notion",
                "action_id": "sync_page",
                "payload": {},
            },
        )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertTrue(body.get("ok"))
        validation = body.get("validation") or {}
        self.assertEqual(str(validation.get("connector_id") or ""), "notion")
        self.assertEqual(str(validation.get("action_id") or ""), "sync_page")
        self.assertFalse(bool(validation.get("can_submit")))
        missing = validation.get("missing_fields") or []
        self.assertIn("page_id", missing)

    async def test_jobs_batch_endpoint_submits_multiple(self):
        resp = await self.client.post(
            "/api/asset-studio/v1/jobs/batch",
            json={
                "jobs": [
                    {"connector_id": "ffmpeg", "action_id": "version_check", "payload": {"timeout_s": 20}},
                    {"connector_id": "notion", "action_id": "version_check", "payload": {}},
                ]
            },
        )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertGreaterEqual(int(body.get("submitted") or 0), 2)
        self.assertEqual(int(body.get("failed") or 0), 0)

    async def test_jobs_batch_endpoint_reports_validation_errors(self):
        resp = await self.client.post(
            "/api/asset-studio/v1/jobs/batch",
            json={
                "jobs": [
                    {"connector_id": "ffmpeg", "action_id": "version_check", "payload": {}},
                    {"connector_id": "", "action_id": "version_check", "payload": {}},
                    "bad-row",
                ]
            },
        )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertGreaterEqual(int(body.get("submitted") or 0), 1)
        self.assertGreaterEqual(int(body.get("failed") or 0), 2)
        errors = body.get("errors") or []
        self.assertGreaterEqual(len(errors), 2)

    async def test_jobs_recommend_endpoint_returns_recommendation(self):
        resp = await self.client.post(
            "/api/asset-studio/v1/jobs/recommend",
            json={
                "goal": "sync this notion page into my workflow",
                "payload": {"page_id": "abc123"},
            },
        )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertTrue(body.get("ok"))
        rec = body.get("recommendation") or {}
        self.assertEqual(str(rec.get("connector_id") or ""), "notion")
        self.assertEqual(str(rec.get("action_id") or ""), "sync_page")
        self.assertTrue(bool(rec.get("can_submit")))

    async def test_jobs_recommendations_endpoint_returns_top_n(self):
        resp = await self.client.post(
            "/api/asset-studio/v1/jobs/recommendations",
            json={
                "goal": "run a github pull request risk review",
                "payload": {"repo": "org/repo", "pr_number": 7},
                "limit": 3,
            },
        )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertTrue(body.get("ok"))
        self.assertGreaterEqual(int(body.get("count") or 0), 1)
        recommendations = body.get("recommendations") or []
        first = recommendations[0] if recommendations else {}
        self.assertEqual(str(first.get("connector_id") or ""), "github")
        self.assertEqual(str(first.get("action_id") or ""), "pr_risk_scan")
        self.assertTrue(bool(first.get("can_submit")))

    async def test_jobs_recommendations_endpoint_defaults_when_no_keyword_match(self):
        resp = await self.client.post(
            "/api/asset-studio/v1/jobs/recommendations",
            json={
                "goal": "totally unrelated words",
                "payload": {},
                "limit": 2,
            },
        )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertTrue(body.get("ok"))
        recommendations = body.get("recommendations") or []
        self.assertGreaterEqual(len(recommendations), 1)
        first = recommendations[0] if recommendations else {}
        self.assertEqual(str(first.get("connector_id") or ""), "ffmpeg")
        self.assertEqual(str(first.get("action_id") or ""), "version_check")

    async def test_jobs_auto_endpoint_creates_job_when_fields_present(self):
        resp = await self.client.post(
            "/api/asset-studio/v1/jobs/auto",
            json={
                "goal": "sync notion page",
                "payload": {"page_id": "abc123"},
            },
        )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertTrue(body.get("ok"))
        rec = body.get("recommendation") or {}
        self.assertEqual(str(rec.get("connector_id") or ""), "notion")
        job = body.get("job") or {}
        self.assertTrue(str(job.get("job_id") or ""))

    async def test_jobs_auto_endpoint_dry_run_returns_no_job(self):
        resp = await self.client.post(
            "/api/asset-studio/v1/jobs/auto",
            json={
                "goal": "sync notion page",
                "payload": {"page_id": "abc123"},
                "dry_run": True,
            },
        )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertTrue(body.get("ok"))
        self.assertTrue(bool(body.get("dry_run")))
        self.assertIsNone(body.get("job"))

    async def test_jobs_auto_endpoint_waits_for_terminal_status(self):
        resp = await self.client.post(
            "/api/asset-studio/v1/jobs/auto",
            json={
                "goal": "zzzz",
                "payload": {},
                "wait": True,
                "wait_timeout_s": 30,
            },
        )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertTrue(body.get("ok"))
        self.assertTrue(bool(body.get("waited")))
        self.assertFalse(bool(body.get("wait_timed_out")))
        job = body.get("job") or {}
        status = str(job.get("status") or "").lower()
        self.assertIn(status, {"done", "failed", "cancelled"})

    async def test_jobs_auto_endpoint_returns_missing_fields_guidance(self):
        resp = await self.client.post(
            "/api/asset-studio/v1/jobs/auto",
            json={
                "goal": "sync notion page",
                "payload": {},
            },
        )
        self.assertEqual(resp.status, 400)
        body = await resp.json()
        self.assertFalse(body.get("ok"))
        rec = body.get("recommendation") or {}
        missing = rec.get("missing_fields") or []
        self.assertIn("page_id", missing)

    async def test_templates_crud_and_run_flow(self):
        create = await self.client.post(
            "/api/asset-studio/v1/templates",
            json={
                "name": "sync-my-notion",
                "connector_id": "notion",
                "action_id": "sync_page",
                "payload": {"page_id": "abc123"},
            },
        )
        self.assertEqual(create.status, 200)
        create_body = await create.json()
        self.assertTrue(create_body.get("ok"))
        template = create_body.get("template") or {}
        template_id = str(template.get("template_id") or "")
        self.assertTrue(template_id)

        listing = await self.client.get("/api/asset-studio/v1/templates")
        self.assertEqual(listing.status, 200)
        listing_body = await listing.json()
        rows = listing_body.get("templates") or []
        ids = {str(row.get("template_id") or "") for row in rows if isinstance(row, dict)}
        self.assertIn(template_id, ids)

        dry_run = await self.client.post(
            f"/api/asset-studio/v1/templates/{template_id}/run",
            json={"dry_run": True},
        )
        self.assertEqual(dry_run.status, 200)
        dry_run_body = await dry_run.json()
        self.assertTrue(dry_run_body.get("ok"))
        self.assertTrue(bool(dry_run_body.get("dry_run")))
        self.assertFalse(bool(dry_run_body.get("submitted")))
        self.assertIsNone(dry_run_body.get("job"))

        run = await self.client.post(f"/api/asset-studio/v1/templates/{template_id}/run", json={})
        self.assertEqual(run.status, 200)
        run_body = await run.json()
        self.assertTrue(run_body.get("ok"))
        self.assertTrue(bool(run_body.get("submitted")))
        job = run_body.get("job") or {}
        self.assertTrue(str(job.get("job_id") or ""))

        delete = await self.client.delete(f"/api/asset-studio/v1/templates/{template_id}")
        self.assertEqual(delete.status, 200)
        delete_body = await delete.json()
        self.assertTrue(delete_body.get("ok"))
        self.assertTrue(bool(delete_body.get("deleted")))

    async def test_templates_support_tags_favorite_and_filters(self):
        first = await self.client.post(
            "/api/asset-studio/v1/templates",
            json={
                "name": "video-convert-favorite",
                "connector_id": "ffmpeg",
                "action_id": "version_check",
                "payload": {"timeout_s": 20},
                "tags": ["video", "utility"],
                "favorite": True,
            },
        )
        self.assertEqual(first.status, 200)
        first_tpl = (await first.json()).get("template") or {}
        self.assertTrue(bool(first_tpl.get("favorite")))
        first_tags = first_tpl.get("tags") if isinstance(first_tpl.get("tags"), list) else []
        self.assertIn("video", first_tags)

        second = await self.client.post(
            "/api/asset-studio/v1/templates",
            json={
                "name": "docs-sync-non-favorite",
                "connector_id": "notion",
                "action_id": "sync_page",
                "payload": {"page_id": "abc123"},
                "tags": ["docs"],
                "favorite": False,
            },
        )
        self.assertEqual(second.status, 200)

        favorites = await self.client.get("/api/asset-studio/v1/templates?favorite=true")
        self.assertEqual(favorites.status, 200)
        favorites_rows = (await favorites.json()).get("templates") or []
        favorite_names = {str(row.get("name") or "") for row in favorites_rows if isinstance(row, dict)}
        self.assertIn("video-convert-favorite", favorite_names)
        self.assertNotIn("docs-sync-non-favorite", favorite_names)

        by_tag = await self.client.get("/api/asset-studio/v1/templates?tag=video")
        self.assertEqual(by_tag.status, 200)
        tag_rows = (await by_tag.json()).get("templates") or []
        tag_names = {str(row.get("name") or "") for row in tag_rows if isinstance(row, dict)}
        self.assertIn("video-convert-favorite", tag_names)
        self.assertNotIn("docs-sync-non-favorite", tag_names)

    async def test_template_clone_endpoint(self):
        create = await self.client.post(
            "/api/asset-studio/v1/templates",
            json={
                "name": "clone-source-template",
                "connector_id": "ffmpeg",
                "action_id": "version_check",
                "payload": {"timeout_s": 20},
                "tags": ["video", "batch"],
                "favorite": True,
                "pinned": True,
                "pin_index": 2,
            },
        )
        self.assertEqual(create.status, 200)
        source = (await create.json()).get("template") or {}
        source_id = str(source.get("template_id") or "")
        self.assertTrue(source_id)

        clone = await self.client.post(f"/api/asset-studio/v1/templates/{source_id}/clone", json={})
        self.assertEqual(clone.status, 200)
        clone_body = await clone.json()
        self.assertTrue(clone_body.get("ok"))
        cloned = clone_body.get("template") or {}
        self.assertNotEqual(str(cloned.get("template_id") or ""), source_id)
        self.assertEqual(str(cloned.get("connector_id") or ""), "ffmpeg")
        self.assertEqual(str(cloned.get("action_id") or ""), "version_check")
        cloned_payload = cloned.get("payload") if isinstance(cloned.get("payload"), dict) else {}
        self.assertEqual(int(cloned_payload.get("timeout_s") or 0), 20)
        cloned_tags = cloned.get("tags") if isinstance(cloned.get("tags"), list) else []
        self.assertIn("video", cloned_tags)
        self.assertFalse(bool(cloned.get("favorite")))
        self.assertFalse(bool(cloned.get("pinned")))

        clone_named = await self.client.post(
            f"/api/asset-studio/v1/templates/{source_id}/clone",
            json={"name": "clone-target-custom-name"},
        )
        self.assertEqual(clone_named.status, 200)
        clone_named_body = await clone_named.json()
        custom = clone_named_body.get("template") or {}
        self.assertEqual(str(custom.get("name") or ""), "clone-target-custom-name")

    async def test_template_export_import_roundtrip_without_secret(self):
        create = await self.client.post(
            "/api/asset-studio/v1/templates",
            json={
                "name": "export-source-no-secret",
                "connector_id": "ffmpeg",
                "action_id": "version_check",
                "payload": {"timeout_s": 20},
                "tags": ["pack", "video"],
                "favorite": True,
                "pinned": True,
                "pin_index": 5,
            },
        )
        self.assertEqual(create.status, 200)
        source = (await create.json()).get("template") or {}
        source_id = str(source.get("template_id") or "")
        self.assertTrue(source_id)

        webhook_set = await self.client.post(
            f"/api/asset-studio/v1/templates/{source_id}/webhook",
            json={
                "url": "https://example.test/hooks/export-no-secret",
                "secret": "super-secret",
                "enabled": True,
                "timeout_s": 5,
            },
        )
        self.assertEqual(webhook_set.status, 200)

        exported = await self.client.get(f"/api/asset-studio/v1/templates/{source_id}/export")
        self.assertEqual(exported.status, 200)
        bundle = (await exported.json()).get("bundle") or {}
        webhook_bundle = bundle.get("webhook") if isinstance(bundle.get("webhook"), dict) else {}
        self.assertEqual(str(webhook_bundle.get("url") or ""), "https://example.test/hooks/export-no-secret")
        self.assertTrue(bool(webhook_bundle.get("has_secret")))
        self.assertNotIn("secret", webhook_bundle)

        imported = await self.client.post(
            "/api/asset-studio/v1/templates/import",
            json={"bundle": bundle, "name_override": "imported-no-secret"},
        )
        self.assertEqual(imported.status, 200)
        imported_body = await imported.json()
        self.assertTrue(imported_body.get("ok"))
        template = imported_body.get("template") or {}
        self.assertEqual(str(template.get("name") or ""), "imported-no-secret")
        self.assertTrue(bool(template.get("favorite")))
        self.assertTrue(bool(template.get("pinned")))
        self.assertEqual(int(template.get("pin_index") or -1), 5)
        tags = template.get("tags") if isinstance(template.get("tags"), list) else []
        self.assertIn("pack", tags)
        webhook = imported_body.get("webhook") or {}
        self.assertFalse(bool(webhook.get("has_secret")))

    async def test_template_export_import_roundtrip_with_secret(self):
        create = await self.client.post(
            "/api/asset-studio/v1/templates",
            json={
                "name": "export-source-with-secret",
                "connector_id": "ffmpeg",
                "action_id": "version_check",
                "payload": {"timeout_s": 20},
            },
        )
        self.assertEqual(create.status, 200)
        source = (await create.json()).get("template") or {}
        source_id = str(source.get("template_id") or "")
        self.assertTrue(source_id)

        webhook_set = await self.client.post(
            f"/api/asset-studio/v1/templates/{source_id}/webhook",
            json={
                "url": "https://example.test/hooks/export-with-secret",
                "secret": "with-secret",
                "enabled": True,
                "timeout_s": 5,
            },
        )
        self.assertEqual(webhook_set.status, 200)

        exported = await self.client.get(f"/api/asset-studio/v1/templates/{source_id}/export?include_secret=true")
        self.assertEqual(exported.status, 200)
        bundle = (await exported.json()).get("bundle") or {}
        webhook_bundle = bundle.get("webhook") if isinstance(bundle.get("webhook"), dict) else {}
        self.assertEqual(str(webhook_bundle.get("secret") or ""), "with-secret")

        imported = await self.client.post(
            "/api/asset-studio/v1/templates/import",
            json={"bundle": bundle, "name_override": "imported-with-secret"},
        )
        self.assertEqual(imported.status, 200)
        imported_body = await imported.json()
        webhook = imported_body.get("webhook") or {}
        self.assertTrue(bool(webhook.get("has_secret")))

    async def test_template_patch_updates_metadata(self):
        create = await self.client.post(
            "/api/asset-studio/v1/templates",
            json={
                "name": "patchable-template",
                "connector_id": "ffmpeg",
                "action_id": "version_check",
                "payload": {"timeout_s": 20},
                "tags": ["old"],
                "favorite": False,
            },
        )
        self.assertEqual(create.status, 200)
        template_id = str(((await create.json()).get("template") or {}).get("template_id") or "")
        self.assertTrue(template_id)

        patch_resp = await self.client.patch(
            f"/api/asset-studio/v1/templates/{template_id}",
            json={
                "name": "patched-template",
                "tags": ["new", "video"],
                "favorite": True,
                "pinned": True,
                "pin_index": 3,
            },
        )
        self.assertEqual(patch_resp.status, 200)
        patch_body = await patch_resp.json()
        self.assertTrue(patch_body.get("ok"))
        template = patch_body.get("template") or {}
        self.assertEqual(str(template.get("name") or ""), "patched-template")
        self.assertTrue(bool(template.get("favorite")))
        self.assertTrue(bool(template.get("pinned")))
        self.assertEqual(int(template.get("pin_index") or -1), 3)
        tags = template.get("tags") if isinstance(template.get("tags"), list) else []
        self.assertIn("new", tags)
        self.assertIn("video", tags)

    async def test_templates_list_orders_by_pinned_then_pin_index(self):
        first = await self.client.post(
            "/api/asset-studio/v1/templates",
            json={
                "name": "order-a",
                "connector_id": "ffmpeg",
                "action_id": "version_check",
                "payload": {"timeout_s": 20},
                "favorite": False,
                "pinned": True,
                "pin_index": 20,
            },
        )
        self.assertEqual(first.status, 200)
        second = await self.client.post(
            "/api/asset-studio/v1/templates",
            json={
                "name": "order-b",
                "connector_id": "ffmpeg",
                "action_id": "version_check",
                "payload": {"timeout_s": 20},
                "favorite": False,
                "pinned": True,
                "pin_index": 10,
            },
        )
        self.assertEqual(second.status, 200)
        third = await self.client.post(
            "/api/asset-studio/v1/templates",
            json={
                "name": "order-c",
                "connector_id": "ffmpeg",
                "action_id": "version_check",
                "payload": {"timeout_s": 20},
                "favorite": True,
                "pinned": False,
            },
        )
        self.assertEqual(third.status, 200)

        listing = await self.client.get("/api/asset-studio/v1/templates")
        self.assertEqual(listing.status, 200)
        rows = (await listing.json()).get("templates") or []
        names = [str(row.get("name") or "") for row in rows if isinstance(row, dict)]
        self.assertGreaterEqual(len(names), 3)
        self.assertLess(names.index("order-b"), names.index("order-a"))
        self.assertLess(names.index("order-a"), names.index("order-c"))

    async def test_template_webhook_config_crud(self):
        create = await self.client.post(
            "/api/asset-studio/v1/templates",
            json={
                "name": "template-with-webhook",
                "connector_id": "notion",
                "action_id": "sync_page",
                "payload": {"page_id": "abc123"},
            },
        )
        self.assertEqual(create.status, 200)
        template_id = str(((await create.json()).get("template") or {}).get("template_id") or "")
        self.assertTrue(template_id)

        first_get = await self.client.get(f"/api/asset-studio/v1/templates/{template_id}/webhook")
        self.assertEqual(first_get.status, 200)
        first_body = await first_get.json()
        self.assertTrue(first_body.get("ok"))
        self.assertFalse(bool(first_body.get("configured")))
        self.assertIsNone(first_body.get("webhook"))

        set_resp = await self.client.post(
            f"/api/asset-studio/v1/templates/{template_id}/webhook",
            json={
                "url": "https://example.test/hooks/template",
                "secret": "template-secret",
                "enabled": True,
                "timeout_s": 6,
            },
        )
        self.assertEqual(set_resp.status, 200)
        set_body = await set_resp.json()
        self.assertTrue(set_body.get("ok"))
        webhook = set_body.get("webhook") or {}
        self.assertEqual(str(webhook.get("template_id") or ""), template_id)
        self.assertEqual(str(webhook.get("url") or ""), "https://example.test/hooks/template")
        self.assertTrue(bool(webhook.get("has_secret")))
        self.assertTrue(bool(webhook.get("enabled")))

        second_get = await self.client.get(f"/api/asset-studio/v1/templates/{template_id}/webhook")
        self.assertEqual(second_get.status, 200)
        second_body = await second_get.json()
        self.assertTrue(bool(second_body.get("configured")))

        delete_resp = await self.client.delete(f"/api/asset-studio/v1/templates/{template_id}/webhook")
        self.assertEqual(delete_resp.status, 200)
        delete_body = await delete_resp.json()
        self.assertTrue(delete_body.get("ok"))
        self.assertTrue(bool(delete_body.get("deleted")))

        third_get = await self.client.get(f"/api/asset-studio/v1/templates/{template_id}/webhook")
        self.assertEqual(third_get.status, 200)
        third_body = await third_get.json()
        self.assertFalse(bool(third_body.get("configured")))
        self.assertIsNone(third_body.get("webhook"))

    async def test_template_webhook_override_is_used_for_template_jobs(self):
        create = await self.client.post(
            "/api/asset-studio/v1/templates",
            json={
                "name": "ffmpeg-template-webhook-override",
                "connector_id": "ffmpeg",
                "action_id": "version_check",
                "payload": {"timeout_s": 20},
            },
        )
        self.assertEqual(create.status, 200)
        template_id = str(((await create.json()).get("template") or {}).get("template_id") or "")
        self.assertTrue(template_id)

        global_cfg = await self.client.post(
            "/api/asset-studio/v1/webhooks/completion",
            json={
                "url": "https://example.test/hooks/global",
                "secret": "global-secret",
                "enabled": True,
                "timeout_s": 5,
            },
        )
        self.assertEqual(global_cfg.status, 200)

        template_cfg = await self.client.post(
            f"/api/asset-studio/v1/templates/{template_id}/webhook",
            json={
                "url": "https://example.test/hooks/template",
                "secret": "template-secret",
                "enabled": True,
                "timeout_s": 5,
            },
        )
        self.assertEqual(template_cfg.status, 200)

        captured_urls: list[str] = []

        class _FakeWebhookResponse:
            status = 200

            def read(self, _n: int | None = None) -> bytes:
                return b"ok"

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb) -> bool:
                return False

            def getcode(self) -> int:
                return int(self.status)

        def _capture_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
            _ = timeout
            captured_urls.append(str(getattr(request, "full_url", "")))
            return _FakeWebhookResponse()

        with patch("thomas.asset_studio.runtime.urllib.request.urlopen", side_effect=_capture_urlopen):
            run = await self.client.post(
                f"/api/asset-studio/v1/templates/{template_id}/run",
                json={"wait": True, "wait_timeout_s": 30},
            )
            self.assertEqual(run.status, 200)
            run_body = await run.json()
            self.assertTrue(run_body.get("ok"))
            self.assertTrue(bool(run_body.get("submitted")))
            self.assertTrue(bool(run_body.get("waited")))
            self.assertFalse(bool(run_body.get("wait_timed_out")))
            job = run_body.get("job") or {}
            job_id = str(job.get("job_id") or "")
            self.assertTrue(job_id)

            events_resp = await self.client.get(f"/api/asset-studio/v1/jobs/{job_id}/events")
            self.assertEqual(events_resp.status, 200)
            events = (await events_resp.json()).get("events") or []
            kinds = {str(item.get("kind") or "") for item in events if isinstance(item, dict)}
            self.assertIn("webhook_ok", kinds)

        self.assertGreaterEqual(len(captured_urls), 1)
        self.assertTrue(all(url == "https://example.test/hooks/template" for url in captured_urls))

    async def test_template_run_by_name_endpoint(self):
        create = await self.client.post(
            "/api/asset-studio/v1/templates",
            json={
                "name": "run-by-name-template",
                "connector_id": "ffmpeg",
                "action_id": "version_check",
                "payload": {"timeout_s": 20},
            },
        )
        self.assertEqual(create.status, 200)

        run = await self.client.post(
            "/api/asset-studio/v1/templates/by-name/run-by-name-template/run",
            json={"wait": True, "wait_timeout_s": 30},
        )
        self.assertEqual(run.status, 200)
        body = await run.json()
        self.assertTrue(body.get("ok"))
        template = body.get("template") or {}
        self.assertEqual(str(template.get("name") or ""), "run-by-name-template")
        self.assertTrue(bool(body.get("submitted")))
        self.assertTrue(bool(body.get("waited")))
        self.assertFalse(bool(body.get("wait_timed_out")))
        job = body.get("job") or {}
        status = str(job.get("status") or "").lower()
        self.assertIn(status, {"done", "failed", "cancelled"})

    async def test_template_run_favorite_endpoint_uses_top_favorite(self):
        first = await self.client.post(
            "/api/asset-studio/v1/templates",
            json={
                "name": "favorite-low-priority",
                "connector_id": "ffmpeg",
                "action_id": "version_check",
                "payload": {"timeout_s": 20},
                "favorite": True,
                "pinned": True,
                "pin_index": 20,
            },
        )
        self.assertEqual(first.status, 200)
        second = await self.client.post(
            "/api/asset-studio/v1/templates",
            json={
                "name": "favorite-high-priority",
                "connector_id": "ffmpeg",
                "action_id": "version_check",
                "payload": {"timeout_s": 20},
                "favorite": True,
                "pinned": True,
                "pin_index": 1,
                "tags": ["quick"],
            },
        )
        self.assertEqual(second.status, 200)

        run = await self.client.post(
            "/api/asset-studio/v1/templates/run-favorite",
            json={"wait": True, "wait_timeout_s": 30},
        )
        self.assertEqual(run.status, 200)
        body = await run.json()
        self.assertTrue(body.get("ok"))
        template = body.get("template") or {}
        self.assertEqual(str(template.get("name") or ""), "favorite-high-priority")
        self.assertTrue(bool(body.get("submitted")))
        self.assertTrue(bool(body.get("waited")))
        self.assertFalse(bool(body.get("wait_timed_out")))

        run_by_tag = await self.client.post(
            "/api/asset-studio/v1/templates/run-favorite",
            json={"tag": "quick", "wait": True, "wait_timeout_s": 30},
        )
        self.assertEqual(run_by_tag.status, 200)
        by_tag_body = await run_by_tag.json()
        self.assertTrue(by_tag_body.get("ok"))
        by_tag_template = by_tag_body.get("template") or {}
        self.assertEqual(str(by_tag_template.get("name") or ""), "favorite-high-priority")

    async def test_template_run_waits_for_terminal_status(self):
        create = await self.client.post(
            "/api/asset-studio/v1/templates",
            json={
                "name": "ffmpeg-wait-template",
                "connector_id": "ffmpeg",
                "action_id": "version_check",
                "payload": {"timeout_s": 20},
            },
        )
        self.assertEqual(create.status, 200)
        template_id = str(((await create.json()).get("template") or {}).get("template_id") or "")
        self.assertTrue(template_id)

        run = await self.client.post(
            f"/api/asset-studio/v1/templates/{template_id}/run",
            json={"wait": True, "wait_timeout_s": 30},
        )
        self.assertEqual(run.status, 200)
        body = await run.json()
        self.assertTrue(body.get("ok"))
        self.assertTrue(bool(body.get("submitted")))
        self.assertTrue(bool(body.get("waited")))
        self.assertFalse(bool(body.get("wait_timed_out")))
        job = body.get("job") or {}
        status = str(job.get("status") or "").lower()
        self.assertIn(status, {"done", "failed", "cancelled"})

    async def test_template_run_returns_validation_guidance_when_missing_fields(self):
        create = await self.client.post(
            "/api/asset-studio/v1/templates",
            json={
                "name": "broken-notion-sync",
                "connector_id": "notion",
                "action_id": "sync_page",
                "payload": {},
            },
        )
        self.assertEqual(create.status, 200)
        template_id = str(((await create.json()).get("template") or {}).get("template_id") or "")
        self.assertTrue(template_id)

        run = await self.client.post(f"/api/asset-studio/v1/templates/{template_id}/run", json={})
        self.assertEqual(run.status, 400)
        body = await run.json()
        self.assertFalse(body.get("ok"))
        validation = body.get("validation") or {}
        missing = validation.get("missing_fields") or []
        self.assertIn("page_id", missing)

    async def test_job_create_endpoint_waits_for_terminal_status(self):
        create = await self.client.post(
            "/api/asset-studio/v1/jobs",
            json={
                "connector_id": "ffmpeg",
                "action_id": "version_check",
                "payload": {"timeout_s": 20},
                "wait": True,
                "wait_timeout_s": 30,
            },
        )
        self.assertEqual(create.status, 200)
        payload = await create.json()
        self.assertTrue(payload.get("ok"))
        self.assertTrue(bool(payload.get("waited")))
        self.assertFalse(bool(payload.get("wait_timed_out")))
        job = payload.get("job") or {}
        status = str(job.get("status") or "").lower()
        self.assertIn(status, {"done", "failed", "cancelled"})

    async def test_job_lifecycle_and_events(self):
        create = await self.client.post(
            "/api/asset-studio/v1/jobs",
            json={
                "connector_id": "ffmpeg",
                "action_id": "version_check",
                "payload": {"timeout_s": 20},
            },
        )
        self.assertEqual(create.status, 200)
        payload = await create.json()
        self.assertTrue(payload.get("ok"))
        job = payload.get("job") or {}
        job_id = str(job.get("job_id") or "")
        self.assertTrue(job_id)

        terminal = None
        for _ in range(50):
            resp = await self.client.get(f"/api/asset-studio/v1/jobs/{job_id}")
            self.assertEqual(resp.status, 200)
            current = (await resp.json()).get("job") or {}
            status = str(current.get("status") or "").lower()
            if status in {"done", "failed", "cancelled"}:
                terminal = status
                break
            await asyncio.sleep(0.1)
        self.assertIn(terminal, {"done", "failed", "cancelled"})

        events_resp = await self.client.get(f"/api/asset-studio/v1/jobs/{job_id}/events")
        self.assertEqual(events_resp.status, 200)
        events_body = await events_resp.json()
        events = events_body.get("events") or []
        self.assertGreaterEqual(len(events), 1)
        kinds = {str(item.get("kind") or "") for item in events if isinstance(item, dict)}
        self.assertIn("queued", kinds)

    async def test_events_stream_endpoint_returns_sse(self):
        create = await self.client.post(
            "/api/asset-studio/v1/jobs",
            json={
                "connector_id": "ffmpeg",
                "action_id": "version_check",
                "payload": {"timeout_s": 20},
            },
        )
        self.assertEqual(create.status, 200)
        job_id = str(((await create.json()).get("job") or {}).get("job_id") or "")
        self.assertTrue(job_id)
        stream = await self.client.get(f"/api/asset-studio/v1/jobs/{job_id}/events/stream")
        self.assertEqual(stream.status, 200)
        ctype = stream.headers.get("Content-Type", "")
        self.assertIn("text/event-stream", ctype)
        body = await stream.text()
        self.assertIn("data:", body)

    async def test_retry_endpoint_creates_new_job(self):
        create = await self.client.post(
            "/api/asset-studio/v1/jobs",
            json={
                "connector_id": "ffmpeg",
                "action_id": "version_check",
                "payload": {"timeout_s": 20},
            },
        )
        self.assertEqual(create.status, 200)
        first_job = (await create.json()).get("job") or {}
        first_job_id = str(first_job.get("job_id") or "")
        self.assertTrue(first_job_id)

        retry = await self.client.post(f"/api/asset-studio/v1/jobs/{first_job_id}/retry")
        self.assertEqual(retry.status, 200)
        retry_body = await retry.json()
        self.assertTrue(retry_body.get("ok"))
        self.assertEqual(str(retry_body.get("retried_from") or ""), first_job_id)
        second_job = retry_body.get("job") or {}
        second_job_id = str(second_job.get("job_id") or "")
        self.assertTrue(second_job_id)
        self.assertNotEqual(first_job_id, second_job_id)


if __name__ == "__main__":
    unittest.main()
