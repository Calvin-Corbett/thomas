"""Tests for the evolve-loop dashboard API handlers.

The handlers that mutate or run the loop shell out to the CLI (covered by the
CLI + loop tests); here we cover the in-process logic: reading persisted state,
the already-running conflict guard, and the cross-process pause flag.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aiohttp import web

from thomas.forge.anvil.evolve_loop import EvolveLoopState, save_loop_state
from thomas.server.routes.evolve_loop_routes import APP_EVOLVE_TASK, build_evolve_loop_handlers


class _FakeRequest:
    def __init__(self, *, query=None, match_info=None, json_body=None):
        self.query = query or {}
        self.match_info = match_info or {}
        self._json = json_body or {}

    async def json(self):
        return self._json


class _FakeRunningTask:
    def done(self):
        return False


def _no_auth(_request):
    return None


def _handlers(app, root: Path):
    return build_evolve_loop_handlers(app, require_api_access=_no_auth, root_resolver=lambda: root)


def _body(resp: web.Response) -> dict:
    return json.loads(resp.body)


class TestEvolveLoopRoutes(unittest.IsolatedAsyncioTestCase):
    async def test_status_reports_persisted_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_loop_state(root, EvolveLoopState(status="running", posture="auto_safe"))
            app = web.Application()
            # A genuinely-live loop task, so the status route reports the persisted
            # "running" verbatim. (Without a live task the route reconciles a stale
            # "running" down to "idle" — see test_status_reconciles_stale_running.)
            app[APP_EVOLVE_TASK] = _FakeRunningTask()
            handlers = _handlers(app, root)
            resp = await handlers["status"](_FakeRequest())
            payload = _body(resp)
            assert payload["ok"] is True
            assert payload["state"]["status"] == "running"
            assert payload["state"]["posture"] == "auto_safe"
            assert payload["state"]["running_task"] is True

    async def test_status_reconciles_stale_running(self):
        # A persisted "running" with no live subprocess is a crash-orphaned state;
        # the route must report idle so the UI re-enables "Start evolving".
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_loop_state(root, EvolveLoopState(status="running", posture="auto_safe"))
            app = web.Application()
            handlers = _handlers(app, root)
            resp = await handlers["status"](_FakeRequest())
            payload = _body(resp)
            assert payload["state"]["status"] == "idle"
            assert payload["state"]["stale_run"] is True
            assert payload["state"]["running_task"] is False
            assert payload["state"]["posture"] == "auto_safe"

    async def test_status_is_idle_without_a_state_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = web.Application()
            handlers = _handlers(app, Path(tmp))
            resp = await handlers["status"](_FakeRequest())
            payload = _body(resp)
            assert payload["state"]["status"] == "idle"
            assert payload["state"]["pending_count"] == 0

    async def test_start_conflicts_when_loop_already_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = web.Application()
            app[APP_EVOLVE_TASK] = _FakeRunningTask()
            handlers = _handlers(app, Path(tmp))
            resp = await handlers["start"](_FakeRequest(json_body={"posture": "auto_safe"}))
            assert resp.status == 409
            assert _body(resp)["ok"] is False

    async def test_orchestration_status_uses_cli_boundary(self):
        import thomas.server.routes.evolve_loop_routes as mod

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calls = []
            original = mod._run_evolve_cli

            async def fake_cli(cli_root, args):
                calls.append((cli_root, args))
                return {"ok": True, "recipes": [{"id": "senior-council-integration"}], "active_workers": []}

            mod._run_evolve_cli = fake_cli
            try:
                app = web.Application()
                handlers = _handlers(app, root)
                resp = await handlers["orchestration_status"](_FakeRequest())
                payload = _body(resp)
                assert payload["ok"] is True
                assert payload["orchestration"]["recipes"][0]["id"] == "senior-council-integration"
                assert calls == [(root, ["orchestration", "status", "--json"])]
            finally:
                mod._run_evolve_cli = original

    async def test_orchestration_plan_passes_recipe_query(self):
        import thomas.server.routes.evolve_loop_routes as mod

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calls = []
            original = mod._run_evolve_cli

            async def fake_cli(cli_root, args):
                calls.append((cli_root, args))
                return {"ok": True, "recipe": {"id": "custom"}, "run": {"dry_run": True}}

            mod._run_evolve_cli = fake_cli
            try:
                app = web.Application()
                handlers = _handlers(app, root)
                resp = await handlers["orchestration_plan"](_FakeRequest(query={"recipe": "custom"}))
                payload = _body(resp)
                assert payload["ok"] is True
                assert payload["orchestration"]["run"]["dry_run"] is True
                assert calls == [(root, ["orchestration", "plan", "--json", "--recipe", "custom"])]
            finally:
                mod._run_evolve_cli = original

    async def test_pause_writes_cross_process_control_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_loop_state(root, EvolveLoopState(status="running"))
            app = web.Application()
            handlers = _handlers(app, root)
            resp = await handlers["pause"](_FakeRequest())
            assert _body(resp)["ok"] is True
            control = root / ".thomas" / "evolve" / "loop" / "control.json"
            assert control.exists()
            assert json.loads(control.read_text(encoding="utf-8"))["stop"] is True


if __name__ == "__main__":
    unittest.main()
