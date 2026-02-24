from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from thomas.codex.provider import CodexProvider
from thomas.core.config import ModelConfig


class _DummyBridge:
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

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
        out: List[str] = []
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
