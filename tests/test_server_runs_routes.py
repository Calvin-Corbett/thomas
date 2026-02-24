"""Tests for thomas.server.routes.runs (time-travel debugger API)."""

import json
import tempfile
import unittest

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.observability import run_store
from thomas.server.app import create_app


def _seed_run(run_id="test_run_1", session_id="sess_1"):
    """Insert a run + 3 events using the production run_store API."""
    run_store.create_run({
        "run_id": run_id,
        "session_id": session_id,
        "started_at": "2026-01-15T12:00:00+00:00",
        "profile": "default",
        "model_id": "gpt-4o",
        "mode": "chat",
        "thomas_version": "0.42.0",
    })
    run_store.append_event(
        run_id, "prompt",
        {"text": "hello", "role": "user"},
        t_ms=0, seq=0,
    )
    run_store.append_event(
        run_id, "assistant",
        {"text": "hi there", "role": "assistant"},
        t_ms=100, seq=1,
    )
    run_store.append_event(
        run_id, "tool.call",
        {"name": "search", "arguments": "{}"},
        t_ms=200, seq=2,
    )
    run_store.finalize_run(
        run_id, ok=True, error=None,
        iterations=1, tool_calls=1,
        usage={"prompt_tokens": 10, "completion_tokens": 5},
    )


class TestRunsRoutesLocal(AioHTTPTestCase):
    """Test time-travel debugger routes under local access mode."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        super().setUp()

    def tearDown(self) -> None:
        try:
            super().tearDown()
        finally:
            run_store.shutdown(reset_db_path=True)
            self._tmpdir.cleanup()

    async def get_application(self):
        cfg = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
            memory=MemoryConfig(root=self._tmpdir.name),
            server=ServerConfig(access_mode="local"),
        )
        return create_app(cfg)

    # ── GET /api/runs (empty) ──

    async def test_list_runs_empty(self):
        resp = await self.client.get("/api/runs")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertIn("runs", body)
        self.assertEqual(len(body["runs"]), 0)
        self.assertIn("limit", body)
        self.assertIn("offset", body)

    # ── GET /api/runs (with data) ──

    async def test_list_runs_with_data(self):
        _seed_run()
        resp = await self.client.get("/api/runs")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertEqual(len(body["runs"]), 1)
        self.assertEqual(body["runs"][0]["run_id"], "test_run_1")
        self.assertEqual(body["runs"][0]["session_id"], "sess_1")
        self.assertTrue(body["runs"][0]["ok"])

    # ── GET /api/runs?session_id=... (filter) ──

    async def test_list_runs_filter_session(self):
        _seed_run("run_a", "sess_A")
        _seed_run("run_b", "sess_B")
        resp = await self.client.get("/api/runs?session_id=sess_A")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertEqual(len(body["runs"]), 1)
        self.assertEqual(body["runs"][0]["session_id"], "sess_A")
        self.assertEqual(body["filters"]["session_id"], "sess_A")

    # ── GET /api/runs/{run_id} ──

    async def test_get_run(self):
        _seed_run()
        resp = await self.client.get("/api/runs/test_run_1")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertIn("run", body)
        self.assertIn("events", body)
        self.assertEqual(body["run"]["run_id"], "test_run_1")
        self.assertEqual(body["run"]["model_id"], "gpt-4o")
        self.assertEqual(len(body["events"]), 3)

    async def test_get_run_not_found(self):
        resp = await self.client.get("/api/runs/nonexistent")
        self.assertEqual(resp.status, 404)

    # ── GET /api/runs/{run_id}/events (paginated) ──

    async def test_events_pagination(self):
        _seed_run()
        resp = await self.client.get("/api/runs/test_run_1/events?start=0&limit=2")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertEqual(body["run_id"], "test_run_1")
        self.assertEqual(body["total"], 3)
        self.assertEqual(len(body["events"]), 2)
        self.assertEqual(body["start"], 0)
        self.assertEqual(body["limit"], 2)
        # First event
        self.assertEqual(body["events"][0]["event_type"], "prompt")
        self.assertEqual(body["events"][0]["index"], 0)

    async def test_events_for_missing_run(self):
        resp = await self.client.get("/api/runs/ghost/events")
        self.assertEqual(resp.status, 404)

    # ── POST /api/runs/{run_id}/replay/seek ──

    async def test_replay_seek(self):
        _seed_run()
        resp = await self.client.post(
            "/api/runs/test_run_1/replay/seek",
            json={"index": 1},
        )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["event"]["index"], 1)
        self.assertEqual(body["event"]["event_type"], "assistant")

    async def test_replay_seek_out_of_range(self):
        _seed_run()
        resp = await self.client.post(
            "/api/runs/test_run_1/replay/seek",
            json={"index": 999},
        )
        self.assertEqual(resp.status, 404)
        body = await resp.json()
        self.assertFalse(body["ok"])

    # ── POST /api/runs/{run_id}/replay/step ──

    async def test_replay_step_forward(self):
        _seed_run()
        resp = await self.client.post(
            "/api/runs/test_run_1/replay/step",
            json={"index": 0, "delta": 1},
        )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["event"]["index"], 1)

    async def test_replay_step_out_of_range(self):
        _seed_run()
        resp = await self.client.post(
            "/api/runs/test_run_1/replay/step",
            json={"index": 2, "delta": 100},
        )
        self.assertEqual(resp.status, 404)
        body = await resp.json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"], "index_out_of_range")

    # ── GET /api/runs/{run_id}/export.json ──

    async def test_export_json(self):
        _seed_run()
        resp = await self.client.get("/api/runs/test_run_1/export.json")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertEqual(body["schema_version"], 1)
        self.assertIn("run", body)
        self.assertIn("events", body)
        self.assertEqual(body["total_events"], 3)
        self.assertFalse(body["truncated"])

    async def test_export_json_not_found(self):
        resp = await self.client.get("/api/runs/ghost/export.json")
        self.assertEqual(resp.status, 404)

    # ── GET /api/runs/{run_id}/export (zip) ──

    async def test_export_zip(self):
        _seed_run()
        resp = await self.client.get("/api/runs/test_run_1/export")
        self.assertEqual(resp.status, 200)
        ct = resp.headers.get("Content-Type", "")
        self.assertIn("application/zip", ct)
        disp = resp.headers.get("Content-Disposition", "")
        self.assertIn("test_run_1", disp)

    # ── GET /api/runs/{run_id}/replay (NDJSON stream) ──

    async def test_replay_ndjson_stream(self):
        _seed_run()
        resp = await self.client.get("/api/runs/test_run_1/replay")
        self.assertEqual(resp.status, 200)
        ct = resp.headers.get("Content-Type", "")
        self.assertIn("ndjson", ct)

    # ── Redaction ──

    async def test_events_redaction(self):
        """Sensitive fields in event payloads must be redacted."""
        run_store.create_run({
            "run_id": "redact_run",
            "started_at": "2026-01-15T12:00:00+00:00",
        })
        run_store.append_event(
            "redact_run", "tool.call",
            {"name": "api_call", "authorization": "Bearer sk-secret123"},
            t_ms=0, seq=0,
        )
        run_store.append_event(
            "redact_run", "tool.output",
            {"result": "ok", "api_key": "sk-SHOULD_NOT_LEAK"},
            t_ms=10, seq=1,
        )
        resp = await self.client.get("/api/runs/redact_run/events")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        raw = json.dumps(body["events"])
        self.assertNotIn("sk-secret123", raw)
        self.assertNotIn("sk-SHOULD_NOT_LEAK", raw)


class TestRunsRoutesRemoteAuth(AioHTTPTestCase):
    """Verify runs routes require auth in remote mode."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        super().setUp()

    def tearDown(self) -> None:
        try:
            super().tearDown()
        finally:
            run_store.shutdown(reset_db_path=True)
            self._tmpdir.cleanup()

    async def get_application(self):
        cfg = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
            memory=MemoryConfig(root=self._tmpdir.name),
            server=ServerConfig(access_mode="remote", api_token="test-token"),
        )
        return create_app(cfg)

    async def test_list_runs_requires_auth(self):
        no_auth = await self.client.get("/api/runs")
        self.assertEqual(no_auth.status, 401)

        with_auth = await self.client.get(
            "/api/runs",
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(with_auth.status, 200)

    async def test_get_run_requires_auth(self):
        no_auth = await self.client.get("/api/runs/any_id")
        self.assertEqual(no_auth.status, 401)

    async def test_export_requires_auth(self):
        no_auth = await self.client.get("/api/runs/any_id/export.json")
        self.assertEqual(no_auth.status, 401)


if __name__ == "__main__":
    unittest.main()
