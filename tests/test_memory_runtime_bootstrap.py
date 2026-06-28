from __future__ import annotations

import asyncio
import types

import thomas.cli.main as cli_main
import thomas.memory.autonomy as autonomy_mod
import thomas.server.app as server_app
from thomas.core.config import AppConfig, MemoryConfig, ModelConfig
from thomas.core.events import AgentEvent, EventType


def _cfg(tmp_path) -> AppConfig:  # noqa: ANN001
    return AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        memory=MemoryConfig(root=str(tmp_path)),
    )


class _DummyMemoryEngine:
    def __init__(self, _config, *, enable_v2: bool = True, enable_legacy: bool = False):
        self.enable_v2 = bool(enable_v2)
        self.enable_legacy = bool(enable_legacy)
        self.started = False

    def start(self) -> None:
        self.started = True

    def close(self) -> None:
        pass


class _DummyLLM:
    def __init__(self, model_config, **_kwargs):
        self.config = model_config
        self.session_usage = types.SimpleNamespace(prompt_tokens=0, completion_tokens=0, total_tokens=0)

    async def close(self) -> None:
        return None


class _CapturingAgentLoop:
    thread_ids: list[str] = []

    def __init__(self, _config, _llm, _tools, **kwargs):  # noqa: ANN001
        type(self).thread_ids.append(str(kwargs.get("thread_id") or ""))

    async def run(self, _prompt, **_kwargs):  # noqa: ANN001
        if False:
            yield None


class _CapturingMaxIterationsAgentLoop:
    max_iterations: list[int | None] = []
    job_types: list[str | None] = []

    def __init__(self, _config, _llm, _tools, **_kwargs):  # noqa: ANN001
        pass

    async def run(self, _prompt, *, max_iterations: int | None = None, job_type: str | None = None):  # noqa: ANN001
        type(self).max_iterations.append(max_iterations)
        type(self).job_types.append(job_type)
        if False:
            yield None


class _FailedToolAgentLoop:
    def __init__(self, _config, _llm, _tools, **_kwargs):  # noqa: ANN001
        pass

    async def run(self, _prompt, **_kwargs):  # noqa: ANN001
        yield AgentEvent(
            type=EventType.TOOL_RESULT,
            data={
                "tool_id": "tool-1",
                "tool_name": "diff.create",
                "result": "Tool execution failed: old_str not found",
                "result_text": "Tool execution failed: old_str not found",
                "ok": False,
                "duration_ms": 1.0,
            },
        )


def test_cli_build_memory_disables_legacy_by_default(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.delenv("THOMAS_MEMORY_LEGACY_ENABLED", raising=False)
    monkeypatch.setattr(autonomy_mod, "AutonomyMemoryEngine", _DummyMemoryEngine)

    engine = cli_main._build_memory(_cfg(tmp_path))

    assert isinstance(engine, _DummyMemoryEngine)
    assert engine.started is True
    assert engine.enable_v2 is True
    assert engine.enable_legacy is False


def test_server_build_memory_respects_legacy_opt_in(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("THOMAS_MEMORY_LEGACY_ENABLED", "1")
    monkeypatch.setattr(server_app, "AutonomyMemoryEngine", _DummyMemoryEngine)

    engine = server_app._build_memory(_cfg(tmp_path))

    assert isinstance(engine, _DummyMemoryEngine)
    assert engine.started is True
    assert engine.enable_v2 is True
    assert engine.enable_legacy is True


def test_cli_run_chat_uses_isolated_memory_thread_ids(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    _CapturingAgentLoop.thread_ids = []
    monkeypatch.setattr(cli_main, "LLMClient", _DummyLLM)
    monkeypatch.setattr(cli_main, "_build_tools", lambda _config: object())
    monkeypatch.setattr(cli_main, "_build_memory", lambda _config: None)
    monkeypatch.setattr(cli_main, "AgentLoop", _CapturingAgentLoop)

    asyncio.run(cli_main._run_chat(_cfg(tmp_path), "hello", None))
    asyncio.run(cli_main._run_chat(_cfg(tmp_path), "hello again", None))

    assert len(_CapturingAgentLoop.thread_ids) == 2
    assert _CapturingAgentLoop.thread_ids[0].startswith("cli:")
    assert _CapturingAgentLoop.thread_ids[1].startswith("cli:")
    assert _CapturingAgentLoop.thread_ids[0] != _CapturingAgentLoop.thread_ids[1]


def test_cli_run_chat_forwards_explicit_max_iterations(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    _CapturingMaxIterationsAgentLoop.max_iterations = []
    _CapturingMaxIterationsAgentLoop.job_types = []
    monkeypatch.setattr(cli_main, "LLMClient", _DummyLLM)
    monkeypatch.setattr(cli_main, "_build_tools", lambda _config: object())
    monkeypatch.setattr(cli_main, "_build_memory", lambda _config: None)
    monkeypatch.setattr(cli_main, "AgentLoop", _CapturingMaxIterationsAgentLoop)

    asyncio.run(cli_main._run_chat(_cfg(tmp_path), "hello", None, max_iterations=4))

    assert _CapturingMaxIterationsAgentLoop.max_iterations == [4]
    assert _CapturingMaxIterationsAgentLoop.job_types == [None]


def test_cli_run_chat_forwards_job_type(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    _CapturingMaxIterationsAgentLoop.max_iterations = []
    _CapturingMaxIterationsAgentLoop.job_types = []
    monkeypatch.setattr(cli_main, "LLMClient", _DummyLLM)
    monkeypatch.setattr(cli_main, "_build_tools", lambda _config: object())
    monkeypatch.setattr(cli_main, "_build_memory", lambda _config: None)
    monkeypatch.setattr(cli_main, "AgentLoop", _CapturingMaxIterationsAgentLoop)

    asyncio.run(
        cli_main._run_chat(
            _cfg(tmp_path),
            "hello",
            None,
            max_iterations=4,
            job_type="self_development",
        )
    )

    assert _CapturingMaxIterationsAgentLoop.max_iterations == [4]
    assert _CapturingMaxIterationsAgentLoop.job_types == ["self_development"]


def test_cli_run_chat_prints_failed_tool_result_text(tmp_path, monkeypatch, capsys) -> None:  # noqa: ANN001
    monkeypatch.setattr(cli_main, "LLMClient", _DummyLLM)
    monkeypatch.setattr(cli_main, "_build_tools", lambda _config: object())
    monkeypatch.setattr(cli_main, "_build_memory", lambda _config: None)
    monkeypatch.setattr(cli_main, "AgentLoop", _FailedToolAgentLoop)

    asyncio.run(cli_main._run_chat(_cfg(tmp_path), "hello", None))

    out = capsys.readouterr().out
    assert "diff.create" in out
    assert "old_str not found" in out
