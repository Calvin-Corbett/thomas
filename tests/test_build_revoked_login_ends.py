"""Build must stop on a provider 401 instead of retrying a rejected login."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from thomas.core.config import AppConfig, ModelConfig
from thomas.core.events import EventType
from thomas.server.app_keys import APP_CONFIG
from thomas.server.praxis import worker
from thomas.server.praxis.run_channel import RunChannel
from thomas.server.worker_runtime import run_agent_worker_events
from thomas.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_build_child_reports_401_once_and_ends(monkeypatch, tmp_path):
    config = AppConfig(models={"local": ModelConfig(name="local", provider="ollama", model="local")})
    app = {APP_CONFIG: config}
    calls = 0

    async def rejected(*args, **kwargs):
        nonlocal calls
        calls += 1
        yield {
            "type": "error",
            "error": "ChatGPT/Codex HTTP 401: The live Codex login was revoked or invalidated by the server.",
            "provider_status": 401,
            "retryable": True,
        }

    monkeypatch.setattr(worker, "run_agent_worker_events", rejected)
    run = worker.build_read_child_runner(app, tmp_path, model_id="local", run_id="test", profile="local")
    events = await asyncio.wait_for(collect(run("child", "review", "title", "brief")), timeout=1)
    assert calls == 1
    assert len(events) == 1
    assert events[0]["type"] == "error"
    assert events[0]["retryable"] is False
    assert "revoked or invalidated" in events[0]["error"]


@pytest.mark.asyncio
async def test_build_run_channel_ends_with_401_reason_even_if_child_flags_retryable():
    calls = 0

    async def rejected(*args):
        nonlocal calls
        calls += 1
        yield {
            "type": "error",
            "provider_status": 401,
            "retryable": True,
            "error": "ChatGPT/Codex HTTP 401: The live Codex login was revoked or invalidated",
        }

    channel = RunChannel("revoked", rejected)
    child_id = (await channel.spawn([{"kind": "review", "title": "Review", "brief": "Inspect"}]))[0]["agent_id"]
    try:
        await asyncio.wait_for(channel._tasks[child_id], timeout=1)
        result = channel.status([child_id])["agents"][0]
        assert calls == 1
        assert result["state"] == "failed"
        assert "revoked or invalidated" in str(result["events"])
    finally:
        await channel.close()


@pytest.mark.asyncio
async def test_build_run_channel_401_with_quota_metadata_still_ends():
    async def rejected(*args):
        yield {
            "type": "error",
            "provider_status": 401,
            "retryable": True,
            "error": "ChatGPT/Codex HTTP 401: The live Codex login was rejected",
            "quota": {"kind": "quota", "retry_at": 9999999999},
        }

    channel = RunChannel("revoked-quota", rejected)
    child_id = (await channel.spawn([{"kind": "review", "title": "Review", "brief": "Inspect"}]))[0]["agent_id"]
    try:
        await asyncio.wait_for(channel._tasks[child_id], timeout=1)
        result = channel.status([child_id])["agents"][0]
        assert result["state"] == "failed"
        assert "HTTP 401" in str(result["events"])
    finally:
        await channel.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected_retryable"),
    [
        ({"error": "ChatGPT/Codex HTTP 401: revoked", "status": 401, "retryable": True}, False),
        ({"error": "Pass budget exhausted"}, True),
        ({"error": "Connection dropped"}, True),
        ({"error": "Connection dropped", "retryable": False}, True),
        ({"error": "response.failed server error", "status": 500, "retryable": False}, True),
        ({"error": "ChatGPT/Codex HTTP 400: bad request", "status": 400, "retryable": False}, True),
        ({"error": "ChatGPT/Codex HTTP 403: forbidden", "status": 403, "retryable": False}, True),
    ],
)
async def test_worker_preserves_terminal_401_status(tmp_path, failure, expected_retryable):
    from thomas.server import worker_runtime

    class FakeLLM:
        def __init__(self, config, **kwargs):
            self.config = config

        def reset_runtime_trace(self):
            pass

        async def close(self):
            pass

    class FakeLoop:
        def __init__(self, *args, **kwargs):
            pass

        async def run(self, *args, **kwargs):
            yield SimpleNamespace(
                type=EventType.AGENT_ERROR,
                data=failure,
            )

    app = {APP_CONFIG: AppConfig(models={"local": ModelConfig(name="local", provider="ollama", model="local")})}
    with (
        patch.object(worker_runtime, "LLMClient", FakeLLM),
        patch.object(worker_runtime, "AgentLoop", FakeLoop),
        patch("thomas.server.app_helpers._build_tools", return_value=ToolRegistry()),
        patch.object(worker_runtime, "record_issue"),
    ):
        events = await collect(
            run_agent_worker_events(app, prompt="x", instructions="y", work_dir=tmp_path, profile="local")
        )
    failures = [event for event in events if event["type"] == "error"]
    assert len(failures) == 1
    assert failures[0].get("provider_status") == (401 if failure.get("status") == 401 else None)
    assert failures[0]["retryable"] is expected_retryable
    assert failures[0]["error"] == failure["error"]


@pytest.mark.asyncio
async def test_statusless_worker_failure_is_retried_by_run_channel(tmp_path, monkeypatch):
    from thomas.server import worker_runtime
    from thomas.server.praxis import run_channel

    class FakeLLM:
        def __init__(self, config, **kwargs):
            self.config = config

        def reset_runtime_trace(self):
            pass

        async def close(self):
            pass

    calls = 0

    class FakeLoop:
        def __init__(self, *args, **kwargs):
            pass

        async def run(self, *args, **kwargs):
            nonlocal calls
            calls += 1
            yield SimpleNamespace(
                type=EventType.AGENT_ERROR,
                data={"error": "Connection dropped", "retryable": False},
            )

    real_sleep = asyncio.sleep

    async def no_backoff(_delay):
        await real_sleep(0)

    monkeypatch.setattr(run_channel.asyncio, "sleep", no_backoff)
    app = {APP_CONFIG: AppConfig(models={"local": ModelConfig(name="local", provider="ollama", model="local")})}

    async def run_child(*_args):
        async for event in run_agent_worker_events(
            app, prompt="x", instructions="y", work_dir=tmp_path, profile="local"
        ):
            yield event

    with (
        patch.object(worker_runtime, "LLMClient", FakeLLM),
        patch.object(worker_runtime, "AgentLoop", FakeLoop),
        patch("thomas.server.app_helpers._build_tools", return_value=ToolRegistry()),
        patch.object(worker_runtime, "record_issue"),
    ):
        channel = RunChannel("retry-statusless", run_child)
        child_id = (await channel.spawn([{"kind": "review", "title": "Review", "brief": "Inspect"}]))[0]["agent_id"]
        try:
            task = channel._tasks[child_id]
            for _ in range(100):
                if calls >= 2:
                    break
                await real_sleep(0.01)
            assert calls >= 2
            result = channel.status([child_id])["agents"][0]
            assert any(event.get("type") == "retry" for event in result["events"])
            assert result["state"] in {"retrying", "running"}
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await channel.close()


async def collect(events):
    return [event async for event in events]
