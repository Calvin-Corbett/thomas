"""Codex LLM provider — adapts CodexBridge to Thomas's StreamEvent interface.

This makes Codex look like any other LLM provider to the agent loop.
Instead of sending HTTP requests, it routes through the codex app-server
which handles auth, tool execution, and model routing using your ChatGPT
subscription.
"""

from __future__ import annotations

import logging
import tempfile
import inspect
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from thomas.codex.bridge import CodexBridge, CodexBridgeError
from thomas.core.config import ModelConfig
from thomas.core.llm import StreamEvent, TokenUsage

log = logging.getLogger(__name__)


class CodexProvider:
    """Drop-in replacement for LLMClient that routes through Codex.

    The agent loop calls stream_chat(messages, tools) — this provider
    translates that into codex app-server turn/start calls and streams
    back the same StreamEvent types the agent loop expects.
    """

    def __init__(self, config: ModelConfig, bridge: CodexBridge | None = None):
        self.config = config
        self.session_usage = TokenUsage()
        self._bridge = bridge
        self._owns_bridge = bridge is None

    async def _get_bridge(self) -> CodexBridge:
        if self._bridge is None:
            self._bridge = CodexBridge(cwd=None)
            await self._bridge.start()

            # Check auth
            acct = await self._bridge.check_auth()
            if not acct.logged_in:
                log.info("Not logged in to ChatGPT — starting login flow...")
                acct = await self._bridge.login_chatgpt()
                log.info("Logged in as %s (%s plan)", acct.email, acct.plan_type)

        return self._bridge

    async def close(self) -> None:
        if self._bridge and self._owns_bridge:
            await self._bridge.stop()
            self._bridge = None

    def _no_tools_cwd(self) -> str:
        """Workspace used for no-tools conversational turns.

        Keep this separate from the project root so Codex does not discover
        repo-specific AGENTS/bootstrap files and trigger command churn for
        simple chat messages.
        """
        root = Path(tempfile.gettempdir()) / "thomas_codex_no_tools"
        root.mkdir(parents=True, exist_ok=True)
        return str(root)

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
        bridge = await self._get_bridge()

        # Extract the last user message to send as the turn input
        text = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    # Multimodal: extract text parts
                    parts = []
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            parts.append(part.get("text", ""))
                        elif isinstance(part, str):
                            parts.append(part)
                    text = "\n".join(parts)
                break

        if not text:
            yield StreamEvent(type="error", data={"error": "No user message found"})
            yield StreamEvent(type="done")
            return

        # Extract system prompt to use as Codex instructions.
        # Without this, the Codex model never sees Thomas's personality,
        # identity, or conversation instructions — it just acts like a
        # raw coding assistant.
        instructions = ""
        for msg in messages:
            if msg.get("role") == "system":
                content = msg.get("content", "")
                if isinstance(content, str) and content.strip():
                    instructions = content.strip()
                    break

        model = self.config.model or ""
        effort = self.config.reasoning_effort or "medium"
        allow_tools = bool(tools)
        chat_cwd = self._no_tools_cwd() if not allow_tools else None

        # Map tool ids to names so tool_output can include a useful label.
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

                elif etype == "done":
                    yield StreamEvent(type="done")
                    return

        except CodexBridgeError as e:
            yield StreamEvent(type="error", data={"error": str(e)})
            yield StreamEvent(type="done")

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Non-streaming chat completion through Codex."""
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []

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

        return {
            "text": "".join(text_parts),
            "tool_calls": tool_calls,
            "usage": TokenUsage(),
        }
