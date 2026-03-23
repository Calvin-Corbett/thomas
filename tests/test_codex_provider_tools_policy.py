from __future__ import annotations

import asyncio
from typing import Any

from thomas.core.config import ModelConfig
from thomas.marketplace.codex.bridge import CodexBridgeError
from thomas.marketplace.codex.provider import CodexProvider


class _DummyBridge:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def chat(
        self,
        text: str,
        *,
        model: str = "",
        cwd: str | None = None,
        allow_tools: bool = True,
    ):  # noqa: ANN001
        self.calls.append(
            {
                "text": text,
                "model": model,
                "cwd": cwd,
                "allow_tools": bool(allow_tools),
            }
        )
        yield {"type": "tool_start", "id": "t1", "name": "cmd /c echo hello"}
        yield {"type": "tool_output", "id": "t1", "output": "hello\r\n", "exit_code": 0}
        yield {"type": "text", "text": "hi"}
        yield {"type": "done"}


def _collect_event_types(provider: CodexProvider, tools):  # noqa: ANN001
    async def _run():
        out: list[str] = []
        async for evt in provider.stream_chat([{"role": "user", "content": "yo"}], tools=tools):
            out.append(str(evt.type))
        return out

    return asyncio.run(_run())


def test_codex_provider_blocks_tool_events_when_tools_disabled() -> None:
    bridge = _DummyBridge()
    provider = CodexProvider(
        ModelConfig(name="codex", provider="codex", model="gpt-5.2-codex"),
        bridge=bridge,  # type: ignore[arg-type]
    )

    event_types = _collect_event_types(provider, tools=None)

    assert bridge.calls and bridge.calls[0].get("allow_tools") is False
    assert isinstance(bridge.calls[0].get("cwd"), str) and bridge.calls[0].get("cwd")
    assert "tool_call_start" not in event_types
    assert "tool_call_end" not in event_types
    assert event_types[-2:] == ["token", "done"]


def test_codex_provider_allows_tool_events_when_tools_enabled() -> None:
    bridge = _DummyBridge()
    provider = CodexProvider(
        ModelConfig(name="codex", provider="codex", model="gpt-5.2-codex"),
        bridge=bridge,  # type: ignore[arg-type]
    )

    event_types = _collect_event_types(provider, tools=[{"type": "function", "function": {"name": "noop"}}])

    assert bridge.calls and bridge.calls[0].get("allow_tools") is True
    assert bridge.calls[0].get("cwd") is None
    assert event_types == ["tool_call_start", "tool_call_end", "token", "done"]


class _FlakyBridge:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._attempts = 0

    async def chat(
        self,
        text: str,
        *,
        model: str = "",
        cwd: str | None = None,
        allow_tools: bool = True,
    ):  # noqa: ANN001
        self._attempts += 1
        self.calls.append(
            {
                "text": text,
                "model": model,
                "cwd": cwd,
                "allow_tools": bool(allow_tools),
                "attempt": self._attempts,
            }
        )
        if self._attempts == 1:
            raise CodexBridgeError("stdout closed")
        yield {"type": "text", "text": "recovered"}
        yield {"type": "done"}


def test_codex_provider_retries_once_after_bridge_disconnect() -> None:
    bridge = _FlakyBridge()
    provider = CodexProvider(
        ModelConfig(name="codex", provider="codex", model="gpt-5.2-codex"),
        bridge=bridge,  # type: ignore[arg-type]
    )

    event_types = _collect_event_types(provider, tools=None)

    assert len(bridge.calls) == 2
    assert event_types == ["token", "done"]
