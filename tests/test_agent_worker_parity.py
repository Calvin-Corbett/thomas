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
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from thomas.core.config import AppConfig, ModelConfig
from thomas.core.events import EventType
from thomas.server import worker_runtime
from thomas.server.chat_budget_ledger import get_chat_budget_ledger
from thomas.server.routes.chat_v2_keys import APP_CHAT_BUDGET_LEDGER
from thomas.tools.base import ToolResult


class _FakeLLM:
    """Records construction and confirms close() is awaited (no httpx leak)."""

    instances: list = []

    def __init__(self, *args, **kwargs) -> None:
        self.closed = False
        self.config = args[0] if args else kwargs.get("config")
        type(self).instances.append(self)

    def reset_runtime_trace(self) -> None:
        """Match the production LLM receipt lifecycle used by the worker."""

    def runtime_trace(self) -> dict:
        profile = str(getattr(self.config, "name", "") or "")
        provider = str(getattr(self.config, "provider", "") or "")
        model = str(getattr(self.config, "model", "") or "")
        active = {"profile": profile, "provider": provider, "model": model}
        return {
            "requested": dict(active),
            "active": dict(active),
            "failover_enabled": False,
            "failover_used": False,
            "attempts": [{**active, "status": "success", "retryable": False}],
        }

    async def close(self) -> None:
        self.closed = True


class _FakeAgentLoop:
    """Stands in for AgentLoop: records how it was built and emits a fixed event
    stream that includes a real Thomas filesystem tool call."""

    last_init: dict | None = None
    run_kwargs: dict | None = None
    last_prompt: str = ""

    def __init__(self, config, llm, tools, **kwargs) -> None:  # noqa: ANN001
        type(self).last_init = {"config": config, "llm": llm, "tools": tools, "kwargs": kwargs}
        self.llm = llm

    async def run(self, prompt, **kwargs):  # noqa: ANN001, ANN202
        type(self).last_prompt = str(prompt)
        type(self).run_kwargs = kwargs
        usage = getattr(self.llm, "session_usage", None)
        if usage is not None and int(getattr(usage, "total_tokens", 0) or 0) == 0:
            usage.prompt_tokens = 5
            usage.completion_tokens = 3
            usage.total_tokens = 8
        yield SimpleNamespace(type=EventType.TEXT_DELTA, data={"text": "Building it.\n"})
        yield SimpleNamespace(type=EventType.TOOL_CALL_START, data={"tool_name": "fs.write_file"})
        yield SimpleNamespace(
            type=EventType.TOOL_RESULT,
            data={"tool_name": "fs.write_file", "ok": True, "result_text": "Wrote game.html"},
        )
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
    def test_explicit_tool_contract_prunes_unrelated_worker_tools(self):
        class _Registry:
            def __init__(self) -> None:
                self._tools = {
                    "fs.read_file": object(),
                    "fs.write_file": object(),
                    "shell.exec": object(),
                    "web.search": object(),
                }

            def unregister(self, name):  # noqa: ANN001
                self._tools.pop(name, None)

        registry = _Registry()
        selected = worker_runtime._apply_explicit_tool_contract(
            "Create the files using fs.write_file and then call fs.read_file to verify each one.",
            registry,
        )

        self.assertEqual(selected, frozenset({"fs.read_file", "fs.write_file"}))
        self.assertEqual(set(registry._tools), {"fs.read_file", "fs.write_file"})

    def test_tool_names_without_an_explicit_contract_do_not_prune(self):
        class _Registry:
            def __init__(self) -> None:
                self._tools = {"fs.write_file": object(), "shell.exec": object()}

            def unregister(self, name):  # noqa: ANN001
                self._tools.pop(name, None)

        registry = _Registry()
        selected = worker_runtime._apply_explicit_tool_contract(
            "Compare fs.write_file with shell.exec.",
            registry,
        )

        self.assertEqual(selected, frozenset())
        self.assertEqual(set(registry._tools), {"fs.write_file", "shell.exec"})

    async def test_worker_emits_one_terminal_runtime_receipt_after_late_failover(self):
        class _LateFailoverLLM(_FakeLLM):
            def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
                super().__init__(*args, **kwargs)
                self.final_pass = False

            def runtime_trace(self) -> dict:
                requested = {"profile": "local", "provider": "fixture", "model": "primary"}
                if not self.final_pass:
                    return {
                        "requested": requested,
                        "active": requested,
                        "failover_used": False,
                        "attempts": [{**requested, "status": "success"}],
                    }
                fallback = {"profile": "fallback", "provider": "fixture", "model": "backup"}
                return {
                    "requested": requested,
                    "active": fallback,
                    "failover_used": True,
                    "attempts": [{**requested, "status": "success"}, {**fallback, "status": "success"}],
                }

        class _LateFailoverLoop:
            def __init__(self, _config, llm, _tools, **_kwargs):  # noqa: ANN001
                self.llm = llm

            async def run(self, _prompt, **_kwargs):  # noqa: ANN001, ANN202
                yield SimpleNamespace(type=EventType.TEXT_DELTA, data={"text": "draft"})
                self.llm.final_pass = True
                yield SimpleNamespace(type=EventType.AGENT_DONE, data={"text": "final from fallback"})

        with TemporaryDirectory() as tmp:
            app = _app_with_model("fixture", "primary", "local")
            with (
                patch.object(worker_runtime, "LLMClient", _LateFailoverLLM),
                patch.object(worker_runtime, "AgentLoop", _LateFailoverLoop),
                patch("thomas.server.app_helpers._build_tools", return_value=SimpleNamespace(_tools={})),
            ):
                events = [
                    event
                    async for event in worker_runtime.run_agent_worker_events(
                        app,
                        prompt="Return a final answer.",
                        instructions="Answer.",
                        work_dir=tmp,
                        profile="local",
                    )
                ]

        runtime_events = [event for event in events if event["type"] == "model_runtime"]
        self.assertEqual(len(runtime_events), 1)
        self.assertEqual(runtime_events[0]["runtime"]["active"]["model"], "backup")
        self.assertIs(runtime_events[0]["runtime"]["failover_used"], True)
        self.assertLess(
            events.index(runtime_events[0]), next(i for i, event in enumerate(events) if event["type"] == "done")
        )

    async def test_worker_materializes_explicit_fenced_artifacts_from_prose(self):
        prose = (
            "report.md\n```markdown\n# Verified report\nREPORT-MARKER\n```\n"
            "data.csv\n```csv\nItem,Value\nAlpha,17\n```\n"
            "Both files were created."
        )
        calls = []

        class _ProseOnlyLoop:
            def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
                pass

            async def run(self, prompt, **kwargs):  # noqa: ANN001, ANN202
                yield SimpleNamespace(type=EventType.TEXT_DELTA, data={"text": prose})
                yield SimpleNamespace(type=EventType.AGENT_DONE, data={"text": prose})

        class _Registry:
            def __init__(self) -> None:
                self._tools = {
                    "fs.read_file": object(),
                    "fs.write_file": object(),
                    "shell.exec": object(),
                }

            def unregister(self, name):  # noqa: ANN001
                self._tools.pop(name, None)

            async def execute(self, name, args):  # noqa: ANN001, ANN202
                calls.append((name, args))
                return ToolResult(ok=True, data=f"ok {args['path']}")

        _FakeLLM.instances = []
        registry = _Registry()
        with TemporaryDirectory() as tmp:
            app = _app_with_model("ollama", "llama3", "local")
            with (
                patch.object(worker_runtime, "LLMClient", _FakeLLM),
                patch.object(worker_runtime, "AgentLoop", _ProseOnlyLoop),
                patch("thomas.server.app_helpers._build_tools", return_value=registry),
            ):
                events = [
                    event
                    async for event in worker_runtime.run_agent_worker_events(
                        app,
                        prompt=(
                            "Create report.md and data.csv using fs.write_file, then use fs.read_file to verify both."
                        ),
                        instructions="Build in the workspace.",
                        work_dir=tmp,
                        profile="local",
                    )
                ]

        self.assertEqual(
            [(name, args["path"]) for name, args in calls],
            [
                ("fs.write_file", "report.md"),
                ("fs.read_file", "report.md"),
                ("fs.write_file", "data.csv"),
                ("fs.read_file", "data.csv"),
            ],
        )
        self.assertEqual(set(registry._tools), {"fs.read_file", "fs.write_file"})
        self.assertEqual(
            [event["text"] for event in events if event["type"] == "text"],
            ["Created and verified report.md, data.csv."],
        )
        self.assertEqual([event["type"] for event in events].count("tool_output"), 4)

    async def test_explicit_browser_preflight_runs_named_read_only_pair_in_order(self):
        calls = []

        class _Registry:
            async def execute(self, name, args):  # noqa: ANN001, ANN202
                calls.append((name, args))
                if name == "browser.open":
                    return ToolResult(ok=True, data={"title": "Example Domain"})
                if name == "browser.extract":
                    return ToolResult(ok=True, data=["Example Domain"])
                if name == "fs.write_file":
                    return ToolResult(ok=True, data="wrote")
                return ToolResult(ok=True, data="verified")

        events, evidence = await worker_runtime._explicit_browser_preflight(
            (
                "Call browser.open on https://example.com using session_id agentic-parity.\n"
                "Then call browser.extract on that session with selector h1.\n"
                "Call fs.write_file to create agentic_report.md, then fs.read_file to verify it."
            ),
            _Registry(),
        )

        self.assertEqual(
            [name for name, _args in calls],
            ["browser.open", "browser.extract", "fs.write_file", "fs.read_file"],
        )
        self.assertEqual(calls[0][1]["session"], "agentic-parity")
        self.assertEqual(calls[1][1]["selector"], "h1")
        self.assertEqual([event["type"] for event in events], ["tool_start", "tool_output"] * 4)
        self.assertIn("Example Domain", evidence)
        self.assertIn("agentic_report.md", calls[2][1]["path"])
        self.assertIn("https://example.com", calls[2][1]["content"])

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

    async def test_agent_loop_constructor_failure_closes_the_llm(self):
        class _RaisingAgentLoop:
            def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
                raise RuntimeError("constructor failed")

        _FakeLLM.instances = []
        with TemporaryDirectory() as tmp:
            app = _app_with_model("ollama", "llama3", "local")
            with (
                patch.object(worker_runtime, "LLMClient", _FakeLLM),
                patch.object(worker_runtime, "AgentLoop", _RaisingAgentLoop),
                patch("thomas.server.app_helpers._build_tools", return_value=SimpleNamespace(_tools={})),
            ):
                with self.assertRaisesRegex(RuntimeError, "constructor failed"):
                    _ = [
                        event
                        async for event in worker_runtime.run_agent_worker_events(
                            app,
                            prompt="do the work",
                            instructions="work safely",
                            work_dir=tmp,
                            profile="local",
                        )
                    ]

        self.assertTrue(_FakeLLM.instances[-1].closed)

    async def test_closing_after_entered_progress_closes_the_llm(self):
        _FakeLLM.instances = []
        with TemporaryDirectory() as tmp:
            app = _app_with_model("ollama", "llama3", "local")
            with (
                patch.object(worker_runtime, "LLMClient", _FakeLLM),
                patch.object(worker_runtime, "AgentLoop", _FakeAgentLoop),
                patch("thomas.server.app_helpers._build_tools", return_value=SimpleNamespace(_tools={})),
            ):
                stream = worker_runtime.run_agent_worker_events(
                    app,
                    prompt="do the work",
                    instructions="work safely",
                    work_dir=tmp,
                    profile="local",
                ).__aiter__()
                first = await stream.__anext__()
                second = await stream.__anext__()
                await stream.aclose()

        self.assertEqual([first["type"], second["type"]], ["progress", "progress"])
        self.assertTrue(_FakeLLM.instances[-1].closed)

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
        tool_outputs = [e for e in events if e["type"] == "tool_output"]
        self.assertEqual(tool_outputs[0]["result_text"], "Wrote game.html")
        self.assertIn("Browser tools ARE available", _FakeAgentLoop.last_prompt)
        self.assertIn("Carry real returned values", _FakeAgentLoop.last_prompt)
        self.assertIn("Preserve exact requested filenames", _FakeAgentLoop.last_prompt)
        # Worker runs unattended at full autonomy.
        self.assertEqual(_FakeAgentLoop.last_init["kwargs"]["autonomy_level"], 4)
        # httpx client closed in finally -> no resource leak.
        self.assertTrue(_FakeLLM.instances[-1].closed)

    async def test_worker_charges_shared_session_and_daily_budget(self) -> None:
        class _UsageLLM(_FakeLLM):
            def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
                super().__init__(*args, **kwargs)
                self.session_usage = SimpleNamespace(prompt_tokens=0, completion_tokens=0, total_tokens=0)

        with TemporaryDirectory() as tmp:
            budget_path = Path(tmp) / "budget.json"
            ledger = get_chat_budget_ledger(budget_path)
            app = _app_with_model("ollama", "llama3", "local")
            app[APP_CHAT_BUDGET_LEDGER] = ledger
            runtime_policy = {
                "budget_context": {"ledger_path": str(budget_path), "user_id": "u1", "session_id": "s1"},
                "cost": {"session_token_budget": 100, "daily_token_budget": 100, "throttle_on_budget": True},
            }
            with (
                patch.object(worker_runtime, "LLMClient", _UsageLLM),
                patch.object(worker_runtime, "AgentLoop", _FakeAgentLoop),
                patch("thomas.server.app_helpers._build_tools", return_value=SimpleNamespace(_tools={})),
            ):
                events = [
                    event
                    async for event in worker_runtime.run_agent_worker_events(
                        app,
                        prompt="return an answer",
                        instructions="Answer.",
                        work_dir=tmp,
                        profile="local",
                        runtime_policy=runtime_policy,
                    )
                ]
            totals = await ledger.snapshot(user_id="u1", session_id="s1")

        self.assertIn("done", [event["type"] for event in events])
        self.assertEqual(totals.session_tokens, 8)
        self.assertEqual(totals.daily_tokens, 8)

    async def test_answer_only_pass_builds_an_empty_registry(self):
        _FakeLLM.instances = []
        with TemporaryDirectory() as tmp:
            app = _app_with_model("openai_codex", "gpt-5.6-sol", "chatgpt")
            with (
                patch.object(worker_runtime, "LLMClient", _FakeLLM),
                patch.object(worker_runtime, "AgentLoop", _FakeAgentLoop),
                patch("thomas.server.app_helpers._build_tools") as build_tools,
            ):
                events = [
                    event
                    async for event in worker_runtime.run_agent_worker_events(
                        app,
                        prompt="Recommend Chat, Code, or Work and explain why.",
                        instructions="Answer directly.",
                        work_dir=tmp,
                        profile="chatgpt",
                        tools_enabled=False,
                    )
                ]

        build_tools.assert_not_called()
        self.assertEqual(_FakeAgentLoop.last_init["tools"]._tools, {})
        self.assertIn("answer-only model pass", _FakeAgentLoop.last_prompt)
        self.assertIn("substantive text directly", _FakeAgentLoop.last_prompt)
        self.assertIn("done", [event["type"] for event in events])

    async def test_terminal_less_loop_emits_completed_runtime_receipt_before_done(self):
        class _TerminalLessLoop:
            def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
                pass

            async def run(self, prompt, **kwargs):  # noqa: ANN001, ANN202
                if False:
                    yield None

        with TemporaryDirectory() as tmp:
            app = _app_with_model("openai_codex", "gpt-5.6-sol", "chatgpt")
            with (
                patch.object(worker_runtime, "LLMClient", _FakeLLM),
                patch.object(worker_runtime, "AgentLoop", _TerminalLessLoop),
            ):
                events = [
                    event
                    async for event in worker_runtime.run_agent_worker_events(
                        app,
                        prompt="Return a direct answer.",
                        instructions="Answer directly.",
                        work_dir=tmp,
                        profile="chatgpt",
                        tools_enabled=False,
                    )
                ]

        self.assertEqual([event["type"] for event in events[-2:]], ["model_runtime", "done"])
        self.assertEqual(events[-2]["runtime"]["active"]["model"], "gpt-5.6-sol")

    async def test_openai_codex_uses_identical_translation(self):
        local = await self._collect("ollama", "llama3", "local")
        codex = await self._collect("openai_codex", "gpt-5.5", "chatgpt")
        # SAME worker code, different provider -> identical event translation.
        # This IS the provider-agnosticism proof.
        self.assertEqual([e["type"] for e in local], [e["type"] for e in codex])

    async def test_memory_disabled_worker_never_receives_application_memory(self):
        with TemporaryDirectory() as tmp:
            app = _app_with_model("ollama", "llama3", "local")
            app[worker_runtime.APP_MEMORY] = object()
            with (
                patch.object(worker_runtime, "LLMClient", _FakeLLM),
                patch.object(worker_runtime, "AgentLoop", _FakeAgentLoop),
                patch("thomas.server.app_helpers._build_tools", return_value=SimpleNamespace(_tools={})),
            ):
                _ = [
                    event
                    async for event in worker_runtime.run_agent_worker_events(
                        app,
                        prompt="build the requested artifact",
                        instructions="Build in the workspace.",
                        work_dir=tmp,
                        profile="local",
                        memory_enabled=False,
                    )
                ]

        self.assertIsNone(_FakeAgentLoop.last_init["kwargs"]["memory"])

    async def test_explicit_model_and_reasoning_override_provider_defaults(self):
        _FakeLLM.instances = []
        with TemporaryDirectory() as tmp:
            app = _app_with_model("openai_codex", "gpt-5.5", "chatgpt")
            with (
                patch.object(worker_runtime, "LLMClient", _FakeLLM),
                patch.object(worker_runtime, "AgentLoop", _FakeAgentLoop),
                patch("thomas.server.app_helpers._build_tools", return_value=SimpleNamespace(_tools={})),
            ):
                events = [
                    ev
                    async for ev in worker_runtime.run_agent_worker_events(
                        app,
                        prompt="build the requested artifact",
                        instructions="Build in the workspace.",
                        work_dir=tmp,
                        profile="chatgpt",
                        model_id="gpt-5.6-luna",
                        reasoning_effort="xhigh",
                    )
                ]

        self.assertIn("done", [event["type"] for event in events])
        selected = _FakeLLM.instances[-1].config
        self.assertEqual(selected.model, "gpt-5.6-luna")
        # openai_codex has a provider-wide "medium" override; the user's explicit
        # selection must remain authoritative for delegated work.
        self.assertEqual(selected.reasoning_effort, "xhigh")

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
