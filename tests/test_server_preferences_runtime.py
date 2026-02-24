import json
import os
import tempfile
import unittest
from typing import Any, Dict
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


class _FakeAgentLoopRuntime:
    captured: Dict[str, Any] = {}

    def __init__(self, run_cfg, llm, tools, **kwargs):  # noqa: ANN001
        _FakeAgentLoopRuntime.captured = {
            "llm_temperature": float(getattr(llm.config, "temperature", 0.0) or 0.0),
            "llm_top_p": float(getattr(llm.config, "top_p", 0.0) or 0.0),
            "llm_max_tokens": int(getattr(llm.config, "max_tokens", 0) or 0),
            "llm_max_retries": int(getattr(llm, "_max_retries", 0) or 0),
            "llm_base_retry_delay": float(getattr(llm, "_base_retry_delay", 0.0) or 0.0),
            "llm_request_overrides": dict(getattr(llm, "_request_overrides", {}) or {}),
            "llm_fallback_profiles": [
                str(getattr(cfg, "name", "") or "")
                for cfg in list(getattr(llm, "_fallback_configs", []) or [])
            ],
            "tool_names": [str(t.name) for t in tools.list_tools()],
            "quality_enforce": bool(getattr(getattr(run_cfg, "quality", None), "enforce", False)),
            "quality_require_verification_for_coding": bool(
                getattr(getattr(run_cfg, "quality", None), "require_verification_for_coding", False)
            ),
            "quality_require_tests_for_code_edits": bool(
                getattr(getattr(run_cfg, "quality", None), "require_tests_for_code_edits", False)
            ),
            "quality_require_monolith_guard_for_coding": bool(
                getattr(getattr(run_cfg, "quality", None), "require_monolith_guard_for_coding", False)
            ),
            "ctor_kwargs": dict(kwargs or {}),
        }

    async def run(self, prompt, *, mode="auto", tools_policy="auto", token_economy="optimal", **kwargs):  # noqa: ANN001
        _FakeAgentLoopRuntime.captured["prompt"] = prompt
        _FakeAgentLoopRuntime.captured["run_kwargs"] = {
            "mode": mode,
            "tools_policy": str(tools_policy),
            "token_economy": str(token_economy),
            **dict(kwargs or {}),
        }
        yield AgentEvent(
            type=EventType.AGENT_START,
            data={
                "route": {"path": "general", "confidence": 1.0},
                "mode": str(mode),
                "tools_policy": "auto",
                "autonomy_level": int((_FakeAgentLoopRuntime.captured.get("ctor_kwargs") or {}).get("autonomy_level", 3)),
                "autonomy_name": "Custom",
            },
        )
        yield AgentEvent.text_delta("PREF_RUNTIME_OK")
        yield AgentEvent.agent_done(
            text="PREF_RUNTIME_OK",
            iterations=1,
            tool_calls=0,
            usage={"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
            token_report={"mode": str(mode)},
        )


class _FakeAgentLoopPolicyProbe:
    probe_name: str = "shell.exec"
    probe_args: Dict[str, Any] = {"command": "echo hi", "cwd": "."}
    captured: Dict[str, Any] = {}

    def __init__(self, run_cfg, llm, tools, **kwargs):  # noqa: ANN001
        _ = run_cfg
        _ = llm
        _ = kwargs
        self._tools = tools
        _FakeAgentLoopPolicyProbe.captured = {}

    async def run(self, prompt, *, mode="auto", tools_policy="auto", token_economy="optimal", **kwargs):  # noqa: ANN001
        _ = prompt
        _ = tools_policy
        _ = token_economy
        _ = kwargs
        result = await self._tools.execute(
            str(_FakeAgentLoopPolicyProbe.probe_name or ""),
            dict(_FakeAgentLoopPolicyProbe.probe_args or {}),
        )
        _FakeAgentLoopPolicyProbe.captured = {
            "ok": bool(result.ok),
            "error": str(result.error or ""),
        }
        yield AgentEvent(
            type=EventType.AGENT_START,
            data={
                "route": {"path": "general", "confidence": 1.0},
                "mode": str(mode),
                "tools_policy": "auto",
                "autonomy_level": 3,
                "autonomy_name": "Default",
            },
        )
        yield AgentEvent.agent_done(
            text="POLICY_PROBE_OK",
            iterations=1,
            tool_calls=1,
            usage={"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
            token_report={"mode": str(mode)},
        )


class TestServerPreferencesRuntime(AioHTTPTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._prev_db_path = os.environ.get("THOMAS_DB_PATH")
        self._db_path = f"{self._tmpdir.name}\\prefs_runtime.sqlite"
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
                ),
                "remote": ModelConfig(
                    name="remote",
                    provider="openai_compat",
                    base_url="https://api.example.com/v1",
                    model="remote-model",
                ),
            },
            default_model="local",
            memory=MemoryConfig(root=self._tmpdir.name),
            server=ServerConfig(access_mode="local"),
        )
        return create_app(cfg)

    async def _new_session_id(self) -> str:
        sess_resp = await self.client.post("/api/session/new")
        self.assertEqual(sess_resp.status, 200)
        sid = str((await sess_resp.json()).get("session_id") or "")
        self.assertTrue(sid)
        return sid

    def _session_state(self, sid: str) -> Any:
        token = str(sid or "").strip()
        for value in self.app.values():
            if not isinstance(value, dict):
                continue
            if token not in value:
                continue
            candidate = value.get(token)
            if hasattr(candidate, "conversation") and hasattr(candidate, "profile"):
                return candidate
        raise AssertionError(f"session state not found: {token}")

    async def test_advanced_preferences_are_applied_to_chat_runtime(self):
        sid = await self._new_session_id()
        prefs_patch = {
            "autonomy": {"default_level": "L4"},
            "advanced": {
                "model": {
                    "temperature": 1.2,
                    "top_p": 0.42,
                    "max_output_tokens": 1024,
                    "reasoning_effort": "high",
                    "frequency_penalty": 0.4,
                    "presence_penalty": 0.3,
                    "json_mode": True,
                    "deterministic_seed": 99,
                    "stop_sequences": "END\nDONE",
                },
                "tools": {
                    "allow_shell": False,
                    "allow_file_write": False,
                    "allow_network": True,
                    "tool_timeout_s": 33,
                    "max_parallel_tools": 2,
                },
                "memory": {
                    "include_profile_memory": False,
                    "include_thread_memory": False,
                    "retrieval_top_k": 3,
                    "pinned_context": "Always return concise summaries.",
                },
                "cost": {
                    "max_retries": 4,
                    "retry_backoff_ms": 1200,
                    "model_failover_chain": "remote",
                },
            },
        }
        patch_resp = await self.client.patch("/api/preferences", json=prefs_patch)
        self.assertEqual(patch_resp.status, 200)

        with patch("thomas.server.app.AgentLoop", _FakeAgentLoopRuntime):
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "local",
                    "text": "run the task",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        self.assertTrue(events)
        done_events = [e for e in events if e.get("type") == "done"]
        self.assertEqual(len(done_events), 1)

        captured = dict(_FakeAgentLoopRuntime.captured)
        self.assertAlmostEqual(float(captured.get("llm_temperature") or 0.0), 1.2, places=6)
        self.assertAlmostEqual(float(captured.get("llm_top_p") or 0.0), 0.42, places=6)
        self.assertEqual(int(captured.get("llm_max_tokens") or 0), 1024)
        self.assertEqual(int(captured.get("llm_max_retries") or 0), 5)
        self.assertAlmostEqual(float(captured.get("llm_base_retry_delay") or 0.0), 1.2, places=6)

        request_overrides = captured.get("llm_request_overrides") or {}
        self.assertAlmostEqual(float(request_overrides.get("frequency_penalty") or 0.0), 0.4, places=6)
        self.assertAlmostEqual(float(request_overrides.get("presence_penalty") or 0.0), 0.3, places=6)
        self.assertEqual(int(request_overrides.get("seed") or 0), 99)
        self.assertTrue(bool(request_overrides.get("json_mode", False)))
        self.assertEqual(request_overrides.get("stop"), ["END", "DONE"])

        self.assertEqual(captured.get("llm_fallback_profiles"), ["remote"])

        tool_names = set(captured.get("tool_names") or [])
        self.assertNotIn("shell.exec", tool_names)
        self.assertNotIn("fs.write_file", tool_names)
        self.assertNotIn("diff.create", tool_names)
        self.assertNotIn("diff.apply_patch", tool_names)
        self.assertNotIn("git.commit", tool_names)

        ctor_kwargs = captured.get("ctor_kwargs") or {}
        self.assertEqual(int(ctor_kwargs.get("autonomy_level") or 0), 4)
        self.assertEqual(int(ctor_kwargs.get("max_parallel_tools") or 0), 2)
        self.assertEqual(int(ctor_kwargs.get("tool_timeout_s") or 0), 33)

        run_kwargs = captured.get("run_kwargs") or {}
        self.assertEqual(str(run_kwargs.get("mode") or ""), "thinking")
        self.assertIn("[Pinned context]", str(captured.get("prompt") or ""))
        self.assertIn("Always return concise summaries.", str(captured.get("prompt") or ""))

    async def test_local_only_mode_blocks_remote_profiles(self):
        sid = await self._new_session_id()
        patch_resp = await self.client.patch(
            "/api/preferences",
            json={"advanced": {"privacy": {"local_only_mode": True}}},
        )
        self.assertEqual(patch_resp.status, 200)

        blocked = await self.client.post(
            "/api/chat",
            json={
                "session_id": sid,
                "profile": "remote",
                "text": "run",
            },
        )
        self.assertEqual(blocked.status, 403)
        self.assertIn("local_only_mode", await blocked.text())

    async def test_runtime_and_failover_preferences_override_defaults(self):
        sid = await self._new_session_id()
        patch_resp = await self.client.patch(
            "/api/preferences",
            json={
                "advanced": {
                    "runtime": {
                        "default_mode": "fast",
                        "default_token_economy": "cheap",
                        "max_agent_iterations": 7,
                        "quality_enforce": False,
                        "quality_require_verification_for_coding": False,
                        "quality_require_tests_for_code_edits": True,
                        "quality_require_monolith_guard_for_coding": False,
                    },
                    "failover": {
                        "enabled": False,
                        "chat_auto_failover": True,
                        "fallback_on_auth_error": True,
                        "cooldown_seconds": 12,
                    },
                }
            },
        )
        self.assertEqual(patch_resp.status, 200)

        with patch("thomas.server.app.AgentLoop", _FakeAgentLoopRuntime):
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "local",
                    "text": "runtime defaults probe",
                },
            )
        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        self.assertEqual(len([e for e in events if e.get("type") == "done"]), 1)
        model_runtime = next((e for e in events if e.get("type") == "model_runtime"), {})
        runtime_payload = model_runtime.get("runtime") if isinstance(model_runtime, dict) else {}
        self.assertFalse(bool((runtime_payload or {}).get("failover_enabled", True)))

        captured = dict(_FakeAgentLoopRuntime.captured or {})
        run_kwargs = dict(captured.get("run_kwargs") or {})
        self.assertEqual(str(run_kwargs.get("mode") or ""), "fast")
        self.assertEqual(str(run_kwargs.get("token_economy") or ""), "cheap")
        self.assertEqual(int(run_kwargs.get("max_iterations") or 0), 7)
        self.assertFalse(bool(captured.get("quality_enforce", True)))
        self.assertFalse(bool(captured.get("quality_require_verification_for_coding", True)))
        self.assertTrue(bool(captured.get("quality_require_tests_for_code_edits", False)))
        self.assertFalse(bool(captured.get("quality_require_monolith_guard_for_coding", True)))

    async def test_session_budget_throttle_blocks_when_exhausted(self):
        sid = await self._new_session_id()
        patch_resp = await self.client.patch(
            "/api/preferences",
            json={"advanced": {"cost": {"session_token_budget": 1000, "throttle_on_budget": True}}},
        )
        self.assertEqual(patch_resp.status, 200)
        self._session_state(sid).session_token_spend = 1000

        with patch("thomas.server.app.AgentLoop", _FakeAgentLoopRuntime):
            blocked = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "local",
                    "text": "run",
                },
            )
        self.assertEqual(blocked.status, 429)
        self.assertIn("Session token budget exceeded", await blocked.text())

    async def test_require_command_approval_blocks_shell_exec(self):
        sid = await self._new_session_id()
        patch_resp = await self.client.patch(
            "/api/preferences",
            json={"advanced": {"tools": {"allow_shell": True, "require_command_approval": True}}},
        )
        self.assertEqual(patch_resp.status, 200)

        _FakeAgentLoopPolicyProbe.probe_name = "shell.exec"
        _FakeAgentLoopPolicyProbe.probe_args = {"command": "echo hi", "cwd": "."}
        with patch("thomas.server.app.AgentLoop", _FakeAgentLoopPolicyProbe):
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "local",
                    "text": "probe",
                },
            )
        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        self.assertEqual(len([e for e in events if e.get("type") == "done"]), 1)
        probe = dict(_FakeAgentLoopPolicyProbe.captured or {})
        self.assertFalse(bool(probe.get("ok", True)))
        self.assertIn("require_command_approval", str(probe.get("error") or ""))

    async def test_blocked_commands_policy_blocks_matching_shell_command(self):
        sid = await self._new_session_id()
        patch_resp = await self.client.patch(
            "/api/preferences",
            json={"advanced": {"tools": {"allow_shell": True, "blocked_commands": "curl,wget"}}},
        )
        self.assertEqual(patch_resp.status, 200)

        _FakeAgentLoopPolicyProbe.probe_name = "shell.exec"
        _FakeAgentLoopPolicyProbe.probe_args = {"command": "curl https://example.com", "cwd": "."}
        with patch("thomas.server.app.AgentLoop", _FakeAgentLoopPolicyProbe):
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "local",
                    "text": "probe",
                },
            )
        self.assertEqual(resp.status, 200)
        probe = dict(_FakeAgentLoopPolicyProbe.captured or {})
        self.assertFalse(bool(probe.get("ok", True)))
        self.assertIn("blocked_commands policy", str(probe.get("error") or ""))

    async def test_allowed_paths_policy_blocks_outside_filesystem_access(self):
        sid = await self._new_session_id()
        patch_resp = await self.client.patch(
            "/api/preferences",
            json={"advanced": {"tools": {"allowed_paths": "workspace"}}},
        )
        self.assertEqual(patch_resp.status, 200)

        _FakeAgentLoopPolicyProbe.probe_name = "fs.read_file"
        _FakeAgentLoopPolicyProbe.probe_args = {"path": "..\\outside.txt"}
        with patch("thomas.server.app.AgentLoop", _FakeAgentLoopPolicyProbe):
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "local",
                    "text": "probe",
                },
            )
        self.assertEqual(resp.status, 200)
        probe = dict(_FakeAgentLoopPolicyProbe.captured or {})
        self.assertFalse(bool(probe.get("ok", True)))
        self.assertIn("allowed_paths policy", str(probe.get("error") or ""))

    async def test_auto_tool_threshold_can_force_tools_policy(self):
        sid = await self._new_session_id()
        patch_resp = await self.client.patch(
            "/api/preferences",
            json={"advanced": {"tools": {"auto_tool_threshold": 0.95}}},
        )
        self.assertEqual(patch_resp.status, 200)

        with patch("thomas.server.app.AgentLoop", _FakeAgentLoopRuntime):
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "local",
                    "text": "run with minimal tool usage",
                },
            )
        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        self.assertEqual(len([e for e in events if e.get("type") == "done"]), 1)
        run_kwargs = dict((_FakeAgentLoopRuntime.captured or {}).get("run_kwargs") or {})
        self.assertEqual(str(run_kwargs.get("tools_policy") or ""), "never")


if __name__ == "__main__":
    unittest.main()
