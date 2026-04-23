"""Codex LLM provider â€” adapts CodexBridge to Thomas's StreamEvent interface.

This makes Codex look like any other LLM provider to the agent loop.
Instead of sending HTTP requests, it routes through the codex app-server
which handles auth, tool execution, and model routing using your ChatGPT
subscription.
"""

from __future__ import annotations

import contextlib
import inspect
import logging
from collections.abc import AsyncIterator
from typing import Any

from thomas.core.config import ModelConfig
from thomas.core.llm import StreamEvent, TokenUsage
from thomas.marketplace.codex.bridge import CodexBridge, CodexBridgeError
from thomas.marketplace.codex.provider_helpers import (
    coerce_usage,
    extract_instructions,
    extract_user_text,
    no_tools_cwd,
    tools_cwd,
)

log = logging.getLogger(__name__)


class CodexProvider:
    """Drop-in replacement for LLMClient that routes through Codex.

    The agent loop calls stream_chat(messages, tools) â€” this provider
    translates that into codex app-server turn/start calls and streams
    back the same StreamEvent types the agent loop expects.
    """

    def __init__(self, config: ModelConfig, bridge: CodexBridge | None = None):
        self.config = config
        self.session_usage = TokenUsage()
        self._bridge = bridge
        self._owns_bridge = bridge is None

    async def _get_bridge(self) -> CodexBridge:
        if self._bridge is not None and self._owns_bridge and not self._bridge.is_running:
            with contextlib.suppress(Exception):
                await self._bridge.stop()
            self._bridge = None

        if self._bridge is None:
            self._bridge = CodexBridge(cwd=None)
            await self._bridge.start()

            # Check auth
            acct = await self._bridge.check_auth()
            if not acct.logged_in:
                log.info("Not logged in to ChatGPT â€” starting login flow...")
                acct = await self._bridge.login_chatgpt()
                log.info("Logged in as %s (%s plan)", acct.email, acct.plan_type)

        return self._bridge

    async def close(self) -> None:
        if self._bridge and self._owns_bridge:
            await self._bridge.stop()
            self._bridge = None

    async def _reset_bridge(self) -> None:
        if not self._bridge:
            return
        if self._owns_bridge:
            with contextlib.suppress(Exception):
                await self._bridge.stop()
            self._bridge = None

    def _no_tools_cwd(self) -> str:
        return no_tools_cwd()

    def _tools_cwd(self, text: str = "") -> str:
        return tools_cwd(text)

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream a chat completion through Codex.

        Takes the last user message from the conversation and sends it
        as a turn. The codex app-server manages its own conversation
        history internally.
        """
        text = extract_user_text(messages)

        if not text:
            yield StreamEvent(type="error", data={"error": "No user message found"})
            yield StreamEvent(type="done")
            return

        # Extract system prompt to use as Codex instructions.
        # Without this, the Codex model never sees Thomas's personality,
        # identity, or conversation instructions â€” it just acts like a
        # raw coding assistant.
        instructions = extract_instructions(messages)

        model = self.config.model or ""
        effort = self.config.reasoning_effort or "medium"
        allow_tools = bool(tools)
        chat_cwd = tools_cwd(text) if allow_tools else no_tools_cwd()

        max_bridge_attempts = 2
        for attempt in range(max_bridge_attempts):
            bridge = await self._get_bridge()
            tool_names: dict[str, str] = {}
            try:
                try:
                    event_stream = bridge.chat(
                        text,
                        model=model,
                        effort=effort,
                        cwd=chat_cwd,
                        allow_tools=allow_tools,
                        instructions=instructions,
                    )
                except TypeError:
                    # Backward-compat: older bridge/test doubles may not accept newer kwargs.
                    event_stream = bridge.chat(text, model=model, cwd=chat_cwd, allow_tools=allow_tools)

                if inspect.isawaitable(event_stream):
                    event_stream = await event_stream

                if not hasattr(event_stream, "__aiter__"):
                    yield StreamEvent(
                        type="error",
                        data={"error": "Codex bridge returned non-stream object"},
                    )
                    yield StreamEvent(type="done")
                    return

                async for event in event_stream:
                    etype = event.get("type", "")

                    if etype == "text":
                        yield StreamEvent(type="token", data={"text": event.get("text", "")})

                    elif etype == "tool_start":
                        if not allow_tools:
                            continue
                        tool_id = event.get("id", "")
                        tool_name = event.get("name", "")
                        if tool_id:
                            tool_names[tool_id] = tool_name
                        yield StreamEvent(
                            type="tool_call_start",
                            data={
                                "id": tool_id,
                                "name": tool_name,
                            },
                        )

                    elif etype == "tool_output":
                        if not allow_tools:
                            continue
                        tool_id = event.get("id", "")
                        tool_name = tool_names.get(tool_id, "")
                        yield StreamEvent(
                            type="tool_call_end",
                            data={
                                "id": tool_id,
                                "name": tool_name,
                                "arguments": "",
                                "output": event.get("output", ""),
                                "exit_code": event.get("exit_code"),
                            },
                        )
                        if tool_id:
                            tool_names.pop(tool_id, None)

                    elif etype == "error":
                        yield StreamEvent(type="error", data={"error": event.get("error", "")})

                    elif etype == "usage":
                        usage = coerce_usage(event.get("usage"))
                        if usage is None:
                            continue
                        self.session_usage.add(usage)
                        yield StreamEvent(type="usage", data={"usage": usage})

                    elif etype == "done":
                        yield StreamEvent(type="done")
                        return

                # Defensive: if the bridge stream exits without a terminal event.
                yield StreamEvent(type="done")
                return

            except (CodexBridgeError, ConnectionResetError, BrokenPipeError, OSError) as e:
                is_last_attempt = attempt >= (max_bridge_attempts - 1)
                if not is_last_attempt:
                    log.warning(
                        "Codex bridge stream failed (%s). Resetting bridge and retrying once.",
                        type(e).__name__,
                    )
                    await self._reset_bridge()
                    continue
                yield StreamEvent(type="error", data={"error": str(e)})
                yield StreamEvent(type="done")
                return

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Non-streaming chat completion through Codex."""
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        usage = TokenUsage()

        async for event in self.stream_chat(messages, tools):
            if event.type == "token":
                text_parts.append(event.data.get("text", ""))
            elif event.type == "tool_call_end":
                tool_calls.append(
                    {
                        "id": event.data.get("id", ""),
                        "name": event.data.get("name", ""),
                        "arguments": event.data.get("arguments", ""),
                    }
                )
            elif event.type == "usage":
                usage = event.data.get("usage", usage)

        return {
            "text": "".join(text_parts),
            "tool_calls": tool_calls,
            "usage": usage,
        }
