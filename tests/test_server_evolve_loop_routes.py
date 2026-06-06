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
            handlers = _handlers(app, root)
            resp = await handlers["status"](_FakeRequest())
            payload = _body(resp)
            assert payload["ok"] is True
            assert payload["state"]["status"] == "running"
            assert payload["state"]["posture"] == "auto_safe"
            assert payload["state"]["running_task"] is False

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

    async def test_chat_help_on_empty_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = web.Application()
            handlers = _handlers(app, Path(tmp))
            resp = await handlers["chat"](_FakeRequest(json_body={"message": "   "}))
            assert _body(resp)["action"] == "help"

    async def test_chat_pause_intent_writes_control(self):
        import thomas.server.routes.evolve_loop_routes as mod

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = mod._run_evolve_cli

            async def fake_interpret(_root, _args):
                return {"action": "pause", "reply": "Pausing."}

            mod._run_evolve_cli = fake_interpret
            try:
                app = web.Application()
                handlers = _handlers(app, root)
                resp = await handlers["chat"](_FakeRequest(json_body={"message": "stop evolving"}))
                payload = _body(resp)
                assert payload["action"] == "pause"
                assert (root / ".thomas" / "evolve" / "loop" / "control.json").exists()
            finally:
                mod._run_evolve_cli = original


if __name__ == "__main__":
    unittest.main()
