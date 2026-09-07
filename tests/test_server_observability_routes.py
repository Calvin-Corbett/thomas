from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import patch

from aiohttp import web
from aiohttp.client_exceptions import WSServerHandshakeError
from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, ModelConfig, ServerConfig
from thomas.server import app_routes_init
from thomas.server.app import create_app
from thomas.server.routes.observability import register_observability_routes

_HTTP_ROUTES = (
    "/api/events",
    "/api/metrics",
    "/api/agents/activity",
    "/api/task-bots/executions",
    "/api/tools/usage",
)
_WEBSOCKET_ROUTE = "/ws/events"
_OBSERVABILITY_ROUTES = (*_HTTP_ROUTES, _WEBSOCKET_ROUTE)


def test_registration_rejects_a_missing_access_guard_without_adding_routes() -> None:
    app = web.Application()

    try:
        register_observability_routes(app, require_api_access=None)  # type: ignore[arg-type]
    except TypeError as exc:
        assert str(exc) == "require_api_access must be callable"
    else:
        raise AssertionError("registration accepted a missing API access guard")

    assert list(app.router.routes()) == []


def test_app_route_initialization_injects_the_runtime_access_guard() -> None:
    source = Path(app_routes_init.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    wrappers = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_register_observability_routes"
    ]
    assert len(wrappers) == 1

    register_calls = [
        node
        for node in ast.walk(wrappers[0])
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "register_observability_routes"
    ]
    assert len(register_calls) == 1
    call = register_calls[0]
    assert len(call.args) == 1
    assert isinstance(call.args[0], ast.Name) and call.args[0].id == "app_ref"
    access_keywords = [keyword for keyword in call.keywords if keyword.arg == "require_api_access"]
    assert len(access_keywords) == 1
    assert isinstance(access_keywords[0].value, ast.Name)
    assert access_keywords[0].value.id == "_require_api_access"


class TestServerObservabilityRoutes(AioHTTPTestCase):
    async def get_application(self):
        app = web.Application()
        register_observability_routes(app, require_api_access=lambda request: None)
        return app

    async def test_registration_exposes_exactly_six_guarded_get_routes(self):
        registered = [
            route.resource.canonical
            for route in self.app.router.routes()
            if route.method == "GET" and route.handler.__module__ == "thomas.server.routes.observability"
        ]
        self.assertEqual(registered, list(_OBSERVABILITY_ROUTES))
        self.assertEqual(len(registered), 6)

    async def test_api_events_rejects_invalid_query_params(self):
        bad_limit = await self.client.get("/api/events?limit=oops")
        self.assertEqual(bad_limit.status, 400)
        self.assertIn("invalid limit", await bad_limit.text())

        bad_minutes = await self.client.get("/api/events?minutes=oops")
        self.assertEqual(bad_minutes.status, 400)
        self.assertIn("invalid minutes", await bad_minutes.text())

    async def test_api_agents_activity_returns_presence_payload(self):
        from thomas.server.routes import observability as mod

        original = mod.agent_presence.collect_presence
        mod.agent_presence.collect_presence = lambda: {
            "success": True,
            "repo_root": "repo",
            "generated_at": "now",
            "active_count": 1,
            "agents": [{"agent_id": "Codex 1"}],
            "warnings": [],
            "conflicts": [],
        }
        try:
            response = await self.client.get("/api/agents/activity")
            self.assertEqual(response.status, 200)
            payload = await response.json()
            self.assertEqual(payload["active_count"], 1)
            self.assertEqual(payload["agents"][0]["agent_id"], "Codex 1")
        finally:
            mod.agent_presence.collect_presence = original

    async def test_api_task_bot_executions_returns_runtime_summary(self):
        from thomas.server.routes import observability as mod

        original = mod.task_bot_runtime.read_summary
        mod.task_bot_runtime.read_summary = lambda refresh=True: {
            "execution_count": 2,
            "active_count": 1,
            "executions": [{"execution_id": "exec-1", "task_id": "task-1"}],
        }
        try:
            response = await self.client.get("/api/task-bots/executions")
            self.assertEqual(response.status, 200)
            payload = await response.json()
            self.assertTrue(payload["success"])
            self.assertEqual(payload["task_bots"]["execution_count"], 2)
            self.assertEqual(payload["task_bots"]["executions"][0]["execution_id"], "exec-1")
        finally:
            mod.task_bot_runtime.read_summary = original

    async def test_api_metrics_includes_task_bot_counts(self):
        from thomas.server.routes import observability as mod

        original = mod.task_bot_runtime.read_summary
        mod.task_bot_runtime.read_summary = lambda refresh=True: {
            "active_count": 3,
            "stale_count": 1,
            "awaiting_proof_count": 2,
        }
        try:
            response = await self.client.get("/api/metrics")
            self.assertEqual(response.status, 200)
            payload = await response.json()
            self.assertEqual(payload["metrics"]["task_bot_active"], 3)
            self.assertEqual(payload["metrics"]["task_bot_stale"], 1)
            self.assertEqual(payload["metrics"]["task_bot_awaiting_proof"], 2)
        finally:
            mod.task_bot_runtime.read_summary = original


class TestServerObservabilityRemoteAccess(AioHTTPTestCase):
    async def get_application(self):
        config = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
            server=ServerConfig(access_mode="remote", api_token="observability-token"),
        )
        return create_app(config)

    async def _assert_all_six_rejected(self, *, headers: dict[str, str] | None = None) -> list[str]:
        from thomas.server.routes import observability as mod

        rejected: list[str] = []
        with (
            patch.object(mod.agent_presence, "collect_presence") as collect_presence,
            patch.object(mod.task_bot_runtime, "read_summary") as read_summary,
        ):
            for path in _HTTP_ROUTES:
                with self.subTest(path=path):
                    response = await self.client.get(path, headers=headers)
                    self.assertEqual(response.status, 401)
                    rejected.append(path)

            with self.assertRaises(WSServerHandshakeError) as caught:
                await self.client.ws_connect(_WEBSOCKET_ROUTE, headers=headers)
            self.assertEqual(caught.exception.status, 401)
            rejected.append(_WEBSOCKET_ROUTE)

        collect_presence.assert_not_called()
        read_summary.assert_not_called()
        self.assertEqual(mod._WEBSOCKET_CLIENTS, set())
        return rejected

    async def test_remote_mode_rejects_all_six_routes_without_a_token(self):
        rejected = await self._assert_all_six_rejected()

        self.assertEqual(rejected, list(_OBSERVABILITY_ROUTES))

    async def test_remote_mode_rejects_all_six_routes_with_an_invalid_token(self):
        headers = {"Authorization": "Bearer wrong-token"}
        rejected = await self._assert_all_six_rejected(headers=headers)

        self.assertEqual(rejected, list(_OBSERVABILITY_ROUTES))

    async def test_authenticated_requests_reach_all_six_routes(self):
        from thomas.server.routes import observability as mod

        headers = {"Authorization": "Bearer observability-token"}
        presence = {
            "success": True,
            "repo_root": "repo",
            "generated_at": "now",
            "active_count": 0,
            "agents": [],
            "warnings": [],
            "conflicts": [],
        }
        task_bots = {
            "execution_count": 0,
            "active_count": 0,
            "stale_count": 0,
            "awaiting_proof_count": 0,
            "executions": [],
        }

        reached: list[str] = []
        with (
            patch.object(mod.agent_presence, "collect_presence", return_value=presence),
            patch.object(mod.task_bot_runtime, "read_summary", return_value=task_bots),
        ):
            for path in _HTTP_ROUTES:
                with self.subTest(path=path):
                    response = await self.client.get(path, headers=headers)
                    self.assertEqual(response.status, 200)
                    reached.append(path)

            websocket = await self.client.ws_connect(_WEBSOCKET_ROUTE, headers=headers)
            connected = await websocket.receive_json(timeout=2)
            self.assertEqual(connected["type"], "connected")
            reached.append(_WEBSOCKET_ROUTE)
            await websocket.close()

        self.assertEqual(reached, list(_OBSERVABILITY_ROUTES))
