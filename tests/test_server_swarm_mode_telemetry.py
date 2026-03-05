import json
import os
import tempfile
import unittest
from typing import Any
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.core.events import AgentEvent, EventType
from thomas.server.app import create_app


def _parse_ndjson(blob: str):
    out = []
    for raw in str(blob or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


class _FakeAgentLoopSwarm:
    captured: dict[str, Any] = {}

    def __init__(self, run_cfg, llm, tools, **kwargs):  # noqa: ANN001
        _ = run_cfg
        _ = llm
        _ = tools
        self._ctor_kwargs = dict(kwargs or {})
        _FakeAgentLoopSwarm.captured = {"ctor_kwargs": dict(self._ctor_kwargs)}

    async def run(self, prompt, *, mode="auto", tools_policy="auto", token_economy="optimal", **kwargs):  # noqa: ANN001
        _ = prompt
        _ = token_economy
        _FakeAgentLoopSwarm.captured["run_kwargs"] = {
            "mode": str(mode),
            "tools_policy": str(tools_policy),
            **dict(kwargs or {}),
        }
        yield AgentEvent(
            type=EventType.AGENT_START,
            data={
                "route": {"path": "swarm", "confidence": 1.0},
                "mode": str(mode),
                "tools_policy": str(tools_policy),
                "autonomy_level": int(self._ctor_kwargs.get("autonomy_level", 3) or 3),
                "autonomy_name": "Custom",
            },
        )
        yield AgentEvent.agent_done(
            text="SWARM_TELEMETRY_OK",
            iterations=1,
            tool_calls=0,
        )


class _FakeAgentLoopPolicyProbe:
    probe_name: str = "shell.exec"
    probe_args: dict[str, Any] = {"command": "echo hi", "cwd": "."}
    captured: dict[str, Any] = {}

    def __init__(self, run_cfg, llm, tools, **kwargs):  # noqa: ANN001
        _ = run_cfg
        _ = llm
        self._tools = tools
        self._ctor_kwargs = dict(kwargs or {})
        _FakeAgentLoopPolicyProbe.captured = {"ctor_kwargs": dict(self._ctor_kwargs)}

    async def run(self, prompt, *, mode="auto", tools_policy="auto", token_economy="optimal", **kwargs):  # noqa: ANN001
        _ = prompt
        _ = token_economy
        _FakeAgentLoopPolicyProbe.captured["run_kwargs"] = {
            "mode": str(mode),
            "tools_policy": str(tools_policy),
            **dict(kwargs or {}),
        }
        result = await self._tools.execute(
            str(_FakeAgentLoopPolicyProbe.probe_name or ""),
            dict(_FakeAgentLoopPolicyProbe.probe_args or {}),
        )
        _FakeAgentLoopPolicyProbe.captured["probe"] = {
            "ok": bool(result.ok),
            "error": str(result.error or ""),
        }
        yield AgentEvent(
            type=EventType.AGENT_START,
            data={
                "route": {"path": "swarm", "confidence": 1.0},
                "mode": str(mode),
                "tools_policy": str(tools_policy),
                "autonomy_level": int(self._ctor_kwargs.get("autonomy_level", 3) or 3),
                "autonomy_name": "Custom",
            },
        )
        yield AgentEvent.agent_done(
            text="SWARM_POLICY_PROBE_OK",
            iterations=1,
            tool_calls=1,
        )


class _FakeAgentLoopWithUsage:
    def __init__(self, run_cfg, llm, tools, **kwargs):  # noqa: ANN001
        _ = run_cfg
        _ = llm
        _ = tools
        _ = kwargs

    async def run(self, prompt, *, mode="auto", tools_policy="auto", token_economy="optimal", **kwargs):  # noqa: ANN001
        _ = prompt
        _ = token_economy
        _ = kwargs
        yield AgentEvent(
            type=EventType.AGENT_START,
            data={
                "route": {"path": "swarm", "confidence": 1.0},
                "mode": str(mode),
                "tools_policy": str(tools_policy),
                "autonomy_level": 3,
                "autonomy_name": "Custom",
            },
        )
        yield AgentEvent.agent_done(
            text="SWARM_BUDGET_OK",
            iterations=1,
            tool_calls=0,
            usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
            token_report={"mode": str(mode)},
        )


class _FakeAgentLoopEndNoFinal:
    def __init__(self, run_cfg, llm, tools, **kwargs):  # noqa: ANN001
        _ = run_cfg
        _ = llm
        _ = tools
        _ = kwargs

    async def run(self, prompt, *, mode="auto", tools_policy="auto", token_economy="optimal", **kwargs):  # noqa: ANN001
        _ = prompt
        _ = token_economy
        _ = kwargs
        yield AgentEvent(
            type=EventType.AGENT_START,
            data={
                "route": {"path": "swarm", "confidence": 1.0},
                "mode": str(mode),
                "tools_policy": str(tools_policy),
                "autonomy_level": 3,
                "autonomy_name": "Custom",
            },
        )
        yield AgentEvent(type=EventType.AGENT_END, data={"reason": "planner returned no output"})


class TestServerSwarmModeTelemetry(AioHTTPTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._prev_db_path = os.environ.get("THOMAS_DB_PATH")
        self._db_path = f"{self._tmpdir.name}\\prefs_swarm_runtime.sqlite"
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
            models={
                "local": ModelConfig(
                    name="local",
                    provider="openai_compat",
                    base_url="http://127.0.0.1:11434/v1",
                    model="local-model",
                )
            },
            default_model="local",
            memory=MemoryConfig(root=self._tmpdir.name),
            server=ServerConfig(access_mode="local"),
        )
        with patch(
            "thomas.server.routes.chat_v2.register_chat_v2_routes", side_effect=RuntimeError("legacy-chat-required")
        ):
            return create_app(cfg)

    async def test_swarm_mode_done_includes_usage_fields(self):
        sess_resp = await self.client.post("/api/session/new")
        self.assertEqual(sess_resp.status, 200)
        sid = str((await sess_resp.json()).get("session_id") or "")
        self.assertTrue(sid)

        with patch("thomas.server.routes.chat_aiohttp.AgentLoop", _FakeAgentLoopSwarm):
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "local",
                    "mode": "swarm",
                    "text": "run swarm now",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        route_events = [e for e in events if e.get("type") == "route"]
        self.assertEqual(len(route_events), 1)
        self.assertEqual(str((route_events[0].get("route") or {}).get("path") or ""), "swarm")
        self.assertEqual(str(route_events[0].get("mode") or ""), "auto")

        done_events = [e for e in events if e.get("type") == "done"]
        self.assertEqual(len(done_events), 1)
        done = done_events[0]
        self.assertEqual(done.get("text"), "SWARM_TELEMETRY_OK")
        self.assertEqual(done.get("usage"), {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
        self.assertEqual(done.get("run_usage"), {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
        self.assertEqual(done.get("session_usage"), {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})

    async def test_swarm_mode_respects_tool_policy_wrapper(self):
        sess_resp = await self.client.post("/api/session/new")
        self.assertEqual(sess_resp.status, 200)
        sid = str((await sess_resp.json()).get("session_id") or "")
        self.assertTrue(sid)

        patch_resp = await self.client.patch(
            "/api/preferences",
            json={"advanced": {"tools": {"allow_shell": True, "require_command_approval": True}}},
        )
        self.assertEqual(patch_resp.status, 200)

        _FakeAgentLoopPolicyProbe.probe_name = "shell.exec"
        _FakeAgentLoopPolicyProbe.probe_args = {"command": "echo hi", "cwd": "."}
        with patch("thomas.server.routes.chat_aiohttp.AgentLoop", _FakeAgentLoopPolicyProbe):
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "local",
                    "mode": "swarm",
                    "text": "run swarm now",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        self.assertEqual(len([e for e in events if e.get("type") == "done"]), 1)
        probe = dict((_FakeAgentLoopPolicyProbe.captured or {}).get("probe") or {})
        self.assertFalse(bool(probe.get("ok", True)))
        self.assertIn("require_command_approval", str(probe.get("error") or ""))

    async def test_swarm_mode_bypasses_require_command_approval_for_l4(self):
        sess_resp = await self.client.post("/api/session/new")
        self.assertEqual(sess_resp.status, 200)
        sid = str((await sess_resp.json()).get("session_id") or "")
        self.assertTrue(sid)

        patch_resp = await self.client.patch(
            "/api/preferences",
            json={"advanced": {"tools": {"allow_shell": True, "require_command_approval": True}}},
        )
        self.assertEqual(patch_resp.status, 200)

        _FakeAgentLoopPolicyProbe.probe_name = "shell.exec"
        _FakeAgentLoopPolicyProbe.probe_args = {"command": "echo hi", "cwd": "."}
        with patch("thomas.server.routes.chat_aiohttp.AgentLoop", _FakeAgentLoopPolicyProbe):
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "local",
                    "mode": "swarm",
                    "autonomy_level": 4,
                    "text": "run swarm now",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        self.assertEqual(len([e for e in events if e.get("type") == "done"]), 1)
        probe = dict((_FakeAgentLoopPolicyProbe.captured or {}).get("probe") or {})
        self.assertTrue(bool(probe.get("ok", False)))

    async def test_swarm_mode_done_includes_budget_report_when_advanced_cost_enabled(self):
        sess_resp = await self.client.post("/api/session/new")
        self.assertEqual(sess_resp.status, 200)
        sid = str((await sess_resp.json()).get("session_id") or "")
        self.assertTrue(sid)

        patch_resp = await self.client.patch(
            "/api/preferences",
            json={
                "advanced": {
                    "cost": {
                        "session_token_budget": 1000,
                        "daily_token_budget": 10000,
                        "throttle_on_budget": True,
                    }
                }
            },
        )
        self.assertEqual(patch_resp.status, 200)

        with patch("thomas.server.routes.chat_aiohttp.AgentLoop", _FakeAgentLoopWithUsage):
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "local",
                    "mode": "swarm",
                    "text": "run swarm now",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        done_events = [e for e in events if e.get("type") == "done"]
        self.assertEqual(len(done_events), 1)
        token_report = done_events[0].get("token_report") or {}
        budget = token_report.get("budget") or {}
        self.assertEqual((budget.get("session") or {}).get("used_tokens"), 3)
        self.assertEqual((budget.get("session") or {}).get("budget_tokens"), 1000)

    async def test_swarm_mode_end_without_final_emits_error_event(self):
        sess_resp = await self.client.post("/api/session/new")
        self.assertEqual(sess_resp.status, 200)
        sid = str((await sess_resp.json()).get("session_id") or "")
        self.assertTrue(sid)

        with patch("thomas.server.routes.chat_aiohttp.AgentLoop", _FakeAgentLoopEndNoFinal):
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "local",
                    "mode": "swarm",
                    "text": "run swarm now",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        errors = [e for e in events if e.get("type") == "error"]
        self.assertEqual(len(errors), 1)
        self.assertIn("planner returned no output", str(errors[0].get("error") or "").lower())


if __name__ == "__main__":
    unittest.main()
