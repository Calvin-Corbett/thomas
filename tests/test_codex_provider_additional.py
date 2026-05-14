from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from thomas.core.config import ModelConfig
from thomas.marketplace.codex.bridge import CodexBridgeError
from thomas.marketplace.codex.provider import CodexProvider


async def _collect(provider: CodexProvider, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None):
    events = []
    async for event in provider.stream_chat(messages, tools=tools):
        events.append(event)
    return events


@pytest.mark.asyncio
async def test_get_bridge_bootstraps_login_and_replaces_stopped_owned_bridge(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[_BridgeFactory] = []

    class _BridgeFactory:
        def __init__(self, cwd: str | None = None) -> None:
            self.cwd = cwd
            self.is_running = False
            self.started = 0
            self.stopped = 0
            self.logged_in = False
            created.append(self)

        async def start(self) -> None:
            self.started += 1
            self.is_running = True

        async def stop(self) -> None:
            self.stopped += 1
            self.is_running = False

        async def check_auth(self) -> object:
            return SimpleNamespace(logged_in=self.logged_in, email="user@example.com", plan_type="plus")

        async def login_chatgpt(self) -> object:
            self.logged_in = True
            return SimpleNamespace(logged_in=True, email="user@example.com", plan_type="plus")

    monkeypatch.setattr("thomas.marketplace.codex.provider.CodexBridge", _BridgeFactory)

    provider = CodexProvider(ModelConfig(name="codex", provider="codex", model="gpt-5.4"))
    bridge = await provider._get_bridge()
    assert bridge is created[0]
    assert created[0].started == 1
    assert created[0].logged_in is True

    created[0].is_running = False
    replaced = await provider._get_bridge()
    assert replaced is created[1]
    assert created[0].stopped == 1

    await provider.close()
    assert created[1].stopped == 1


@pytest.mark.asyncio
async def test_stream_chat_handles_missing_user_message_and_non_stream_bridge_object() -> None:
    class _NonStreamBridge:
        async def chat(self, text: str, *, model: str = "", cwd: str | None = None, allow_tools: bool = True):  # noqa: ARG002
            return {"not": "a stream"}

    provider = CodexProvider(
        ModelConfig(name="codex", provider="codex", model="gpt-5.4"),
        bridge=_NonStreamBridge(),  # type: ignore[arg-type]
    )

    missing = await _collect(provider, [{"role": "assistant", "content": "no user"}], tools=None)
    assert [event.type for event in missing] == ["error", "done"]
    assert missing[0].data["error"] == "No user message found"

    non_stream = await _collect(provider, [{"role": "user", "content": "hello"}], tools=None)
    assert [event.type for event in non_stream] == ["error", "done"]
    assert non_stream[0].data["error"] == "Codex bridge returned non-stream object"


@pytest.mark.asyncio
async def test_stream_chat_supports_multimodal_input_and_bridge_typeerror_fallback() -> None:
    class _LegacyBridge:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def chat(self, text: str, *, model: str = "", cwd: str | None = None, allow_tools: bool = True):
            self.calls.append(
                {
                    "text": text,
                    "model": model,
                    "cwd": cwd,
                    "allow_tools": allow_tools,
                }
            )
            yield {"type": "text", "text": "ok"}
            yield {"type": "done"}

    bridge = _LegacyBridge()
    provider = CodexProvider(
        ModelConfig(name="codex", provider="codex", model="gpt-5.4", reasoning_effort="high"),
        bridge=bridge,  # type: ignore[arg-type]
    )
    events = await _collect(
        provider,
        [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": [{"type": "text", "text": "hello"}, "world"]},
        ],
        tools=None,
    )

    assert [event.type for event in events] == ["token", "done"]
    assert bridge.calls == [
        {
            "text": "hello\nworld",
            "model": "gpt-5.4",
            "cwd": provider._no_tools_cwd(),
            "allow_tools": False,
        }
    ]


@pytest.mark.asyncio
async def test_stream_chat_emits_terminal_error_after_final_bridge_failure() -> None:
    class _AlwaysFailsBridge:
        def __init__(self) -> None:
            self.calls = 0

        async def chat(self, text: str, **kwargs: object):
            _ = text
            _ = kwargs
            self.calls += 1
            raise CodexBridgeError("permanent failure")
            yield  # pragma: no cover

    bridge = _AlwaysFailsBridge()
    provider = CodexProvider(
        ModelConfig(name="codex", provider="codex", model="gpt-5.4"),
        bridge=bridge,  # type: ignore[arg-type]
    )
    events = await _collect(provider, [{"role": "user", "content": "hello"}], tools=None)

    assert bridge.calls == 2
    assert [event.type for event in events] == ["error", "done"]
    assert "permanent failure" in events[0].data["error"]


@pytest.mark.asyncio
async def test_chat_wrapper_collects_text_and_tool_calls() -> None:
    class _ToolBridge:
        async def chat(self, text: str, **kwargs: object):
            _ = text
            _ = kwargs
            yield {"type": "tool_start", "id": "tool-1", "name": "ls"}
            yield {"type": "tool_output", "id": "tool-1", "output": "README.md", "exit_code": 0}
            yield {"type": "text", "text": "done"}
            yield {"type": "done"}

    provider = CodexProvider(
        ModelConfig(name="codex", provider="codex", model="gpt-5.4"),
        bridge=_ToolBridge(),  # type: ignore[arg-type]
    )
    payload = await provider.chat(
        [{"role": "user", "content": "show files"}],
        tools=[{"type": "function", "function": {"name": "ls"}}],
    )

    assert payload["text"] == "done"
    assert payload["tool_calls"] == [{"id": "tool-1", "name": "ls", "arguments": ""}]
