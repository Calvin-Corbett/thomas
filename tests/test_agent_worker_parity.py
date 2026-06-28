"""Provider-agnostic worker parity.

Proves the ONE worker (``run_agent_worker_events``) drives the standard
``AgentLoop`` and translates its events into the bridge-style dicts the
delegation layer consumes -- IDENTICALLY regardless of which provider the config
selects.  A Thomas-registry tool flowing through (not a provider-native sandbox
tool) is the signal we are on the shared path, not a per-provider fork.

These tests are fully offline: ``AgentLoop`` and ``LLMClient`` are stubbed so the
test exercises the worker's wiring + event translation, not a live model.
"""

from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from thomas.core.config import AppConfig, ModelConfig
from thomas.core.events import EventType
from thomas.server import worker_runtime


class _FakeLLM:
    """Records construction and confirms close() is awaited (no httpx leak)."""

    instances: list = []

    def __init__(self, *args, **kwargs) -> None:
        self.closed = False
        type(self).instances.append(self)

    async def close(self) -> None:
        self.closed = True


class _FakeAgentLoop:
    """Stands in for AgentLoop: records how it was built and emits a fixed event
    stream that includes a real Thomas filesystem tool call."""

    last_init: dict | None = None
    run_kwargs: dict | None = None

    def __init__(self, config, llm, tools, **kwargs) -> None:  # noqa: ANN001
        type(self).last_init = {"config": config, "llm": llm, "tools": tools, "kwargs": kwargs}

    async def run(self, prompt, **kwargs):  # noqa: ANN001, ANN202
        type(self).run_kwargs = kwargs
        yield SimpleNamespace(type=EventType.TEXT_DELTA, data={"text": "Building it.\n"})
        yield SimpleNamespace(type=EventType.TOOL_CALL_START, data={"tool_name": "fs.write_file"})
        yield SimpleNamespace(type=EventType.TOOL_RESULT, data={"tool_name": "fs.write_file", "ok": True})
        yield SimpleNamespace(
            type=EventType.AGENT_DONE,
            data={"text": "Built game.html", "iterations": 1, "tool_calls": 1},
        )


def _app_with_model(provider: str, model: str, profile: str) -> dict:
    cfg = AppConfig()
    cfg.models = {profile: ModelConfig(name=profile, provider=provider, model=model)}
    cfg.default_model = profile
    return {
        worker_runtime.APP_CONFIG: cfg,
        worker_runtime.APP_SECRETS: None,
        worker_runtime.APP_MEMORY: None,
    }


class TestAgentWorkerParity(unittest.IsolatedAsyncioTestCase):
    async def test_worker_emits_first_progress_before_app_config_access(self):
        # A live provider/model setup can be slow. The delegation layer must get a
        # first event before the worker touches config/model/tool construction, or
        # self-development tasks can falsely fail as "no first event".
        with TemporaryDirectory() as tmp:
            stream = worker_runtime.run_agent_worker_events(
                {},
                prompt="x",
                instructions="y",
                work_dir=tmp,
                profile="local",
            ).__aiter__()
            first = await stream.__anext__()
            await stream.aclose()

        self.assertEqual(first["type"], "progress")
        self.assertIn("initializing", first["text"])

    async def _collect(self, provider: str, model: str, profile: str) -> list[dict]:
        _FakeLLM.instances = []
        with TemporaryDirectory() as tmp:
            app = _app_with_model(provider, model, profile)
            with (
                patch.object(worker_runtime, "LLMClient", _FakeLLM),
                patch.object(worker_runtime, "AgentLoop", _FakeAgentLoop),
                patch("thomas.server.app_helpers._build_tools", return_value=SimpleNamespace(_tools={})),
            ):
                events = [
                    ev
                    async for ev in worker_runtime.run_agent_worker_events(
                        app,
                        prompt="make me a snake game",
                        instructions="Build in the workspace.",
                        work_dir=tmp,
                        profile=profile,
                    )
                ]
        return events

    async def test_local_provider_runs_through_shared_path(self):
        events = await self._collect("ollama", "llama3", "local")
        types = [e["type"] for e in events]
        self.assertEqual(types[:2], ["progress", "progress"])
        self.assertIn("tool_start", types)
        self.assertIn("tool_output", types)
        self.assertIn("done", types)
        tool_starts = [e for e in events if e["type"] == "tool_start"]
        # A Thomas-registry tool flowed through -> shared path, not a native fork.
        self.assertEqual(tool_starts[0]["name"], "fs.write_file")
        # Worker runs unattended at full autonomy.
        self.assertEqual(_FakeAgentLoop.last_init["kwargs"]["autonomy_level"], 4)
        # httpx client closed in finally -> no resource leak.
        self.assertTrue(_FakeLLM.instances[-1].closed)

    async def test_openai_codex_uses_identical_translation(self):
        local = await self._collect("ollama", "llama3", "local")
        codex = await self._collect("openai_codex", "gpt-5.5", "chatgpt")
        # SAME worker code, different provider -> identical event translation.
        # This IS the provider-agnosticism proof.
        self.assertEqual([e["type"] for e in local], [e["type"] for e in codex])

    async def test_run_config_confines_tools_to_workspace(self):
        with TemporaryDirectory() as tmp:
            app = _app_with_model("ollama", "llama3", "local")
            with (
                patch.object(worker_runtime, "LLMClient", _FakeLLM),
                patch.object(worker_runtime, "AgentLoop", _FakeAgentLoop),
                patch("thomas.server.app_helpers._build_tools", return_value=SimpleNamespace(_tools={})),
            ):
                _ = [
                    ev
                    async for ev in worker_runtime.run_agent_worker_events(
                        app, prompt="x", instructions="y", work_dir=tmp, profile="local"
                    )
                ]
            run_cfg = _FakeAgentLoop.last_init["config"]
            # Tools are pointed at the workspace via sandbox_root (no os.chdir).
            self.assertEqual(run_cfg.tools.sandbox_root, str(tmp))
            self.assertTrue(run_cfg.tools.allow_shell)

    async def test_agent_end_reports_failure_not_false_success(self):
        # A denied / interrupted run ends with AGENT_END (which does NOT set
        # state.error). The worker must surface this as an error, never a "done".
        class _EndingLoop:
            def __init__(self, *a, **k) -> None:  # noqa: ANN002, ANN003
                pass

            async def run(self, prompt, **kwargs):  # noqa: ANN001, ANN202
                yield SimpleNamespace(type=EventType.TEXT_DELTA, data={"text": "starting"})
                yield SimpleNamespace(
                    type=EventType.AGENT_END,
                    data={"reason": "suspicious_prompt_denied", "message": "blocked"},
                )

        _FakeLLM.instances = []
        with TemporaryDirectory() as tmp:
            app = _app_with_model("ollama", "llama3", "local")
            with (
                patch.object(worker_runtime, "LLMClient", _FakeLLM),
                patch.object(worker_runtime, "AgentLoop", _EndingLoop),
                patch("thomas.server.app_helpers._build_tools", return_value=SimpleNamespace(_tools={})),
            ):
                events = [
                    ev
                    async for ev in worker_runtime.run_agent_worker_events(
                        app, prompt="x", instructions="y", work_dir=tmp, profile="local"
                    )
                ]
        types = [e["type"] for e in events]
        self.assertIn("error", types)
        self.assertNotIn("done", types)
        # Even on the abnormal-end path the httpx client is still closed.
        self.assertTrue(_FakeLLM.instances[-1].closed)

    def test_resolve_profile_precedence_role_over_chat_over_default(self):
        # Calvin's design: a per-specialist (role) override wins; otherwise the
        # chat's model is the pipeline default.
        cfg = AppConfig()
        cfg.models = {
            "local": ModelConfig(name="local", provider="ollama", model="llama3"),
            "chatgpt": ModelConfig(name="chatgpt", provider="openai_codex", model="gpt-5.5"),
        }
        cfg.default_model = "local"
        with patch(
            "thomas.server.model_preferences.read_user_model_role_preferences",
            return_value=("chatgpt", ""),
        ):
            # role override (chatgpt) beats the chat's model (local)
            self.assertEqual(worker_runtime._resolve_profile(cfg, "local", role="coding"), "chatgpt")
        with patch(
            "thomas.server.model_preferences.read_user_model_role_preferences",
            return_value=("", ""),
        ):
            # no role override -> the chat's model is the default
            self.assertEqual(worker_runtime._resolve_profile(cfg, "chatgpt", role="coding"), "chatgpt")

    async def test_worker_scales_iterations_with_effort(self):
        # The worker's pass budget scales with Effort (after the Autonomy coupling),
        # and it threads the coupled level through as token_economy.
        async def _run(effort: str, autonomy: int) -> dict:
            _FakeLLM.instances = []
            with TemporaryDirectory() as tmp:
                app = _app_with_model("anthropic", "claude", "local")  # no per-model override
                with (
                    patch.object(worker_runtime, "LLMClient", _FakeLLM),
                    patch.object(worker_runtime, "AgentLoop", _FakeAgentLoop),
                    patch("thomas.server.app_helpers._build_tools", return_value=SimpleNamespace(_tools={})),
                ):
                    _ = [
                        ev
                        async for ev in worker_runtime.run_agent_worker_events(
                            app,
                            prompt="x",
                            instructions="y",
                            work_dir=tmp,
                            profile="local",
                            effort=effort,
                            autonomy_level=autonomy,
                        )
                    ]
            return dict(_FakeAgentLoop.run_kwargs or {})

        brisk = await _run("brisk", 4)
        exhaustive = await _run("exhaustive", 4)
        # Brisk @ L4 auto-promotes to Diligent (optimal); Exhaustive stays max.
        self.assertEqual(brisk["token_economy"], "optimal")
        self.assertEqual(exhaustive["token_economy"], "max")
        self.assertLess(brisk["max_iterations"], exhaustive["max_iterations"])

    async def test_worker_tolerates_missing_max_agent_iterations(self):
        _FakeLLM.instances = []
        with TemporaryDirectory() as tmp:
            app = _app_with_model("anthropic", "claude", "local")
            app[worker_runtime.APP_CONFIG].max_agent_iterations = None
            with (
                patch.object(worker_runtime, "LLMClient", _FakeLLM),
                patch.object(worker_runtime, "AgentLoop", _FakeAgentLoop),
                patch("thomas.server.app_helpers._build_tools", return_value=SimpleNamespace(_tools={})),
            ):
                events = [
                    ev
                    async for ev in worker_runtime.run_agent_worker_events(
                        app,
                        prompt="x",
                        instructions="y",
                        work_dir=tmp,
                        profile="local",
                        effort="exhaustive",
                        autonomy_level=4,
                    )
                ]
        self.assertIn("done", [event["type"] for event in events])
        self.assertEqual(_FakeAgentLoop.run_kwargs["token_economy"], "max")
        self.assertEqual(_FakeAgentLoop.run_kwargs["max_iterations"], 25)

    async def test_worker_forwards_self_development_job_type(self):
        _FakeLLM.instances = []
        with TemporaryDirectory() as tmp:
            app = _app_with_model("anthropic", "claude", "local")
            with (
                patch.object(worker_runtime, "LLMClient", _FakeLLM),
                patch.object(worker_runtime, "AgentLoop", _FakeAgentLoop),
                patch("thomas.server.app_helpers._build_tools", return_value=SimpleNamespace(_tools={})),
            ):
                _ = [
                    ev
                    async for ev in worker_runtime.run_agent_worker_events(
                        app,
                        prompt="fix Thomas in the live repo",
                        instructions="Do live repo work.",
                        work_dir=tmp,
                        profile="local",
                        job_type="self_development",
                    )
                ]
        self.assertEqual(_FakeAgentLoop.run_kwargs["job_type"], "self_development")


if __name__ == "__main__":
    unittest.main()
