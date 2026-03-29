"""Tool Specialist — executes domain tools from Thomas's 132 modules.

This specialist handles tasks that require invoking Thomas's domain
tools (bioinformatics, CAD, telecom, blockchain, IoT, robotics,
climate, energy, gaming, music, engineering, filesystem, etc.).

It uses the LLM to decide which tools to call, then executes them
with capability-token permission checking.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from thomas.marketplace.orchestrator.protocol import CapabilityToken, DelegationContract
from thomas.marketplace.specialists.base import BaseSpecialist

log = logging.getLogger(__name__)


class ToolSpecialist(BaseSpecialist):
    """Domain tool execution specialist for Thomas's 132 tool modules."""

    @property
    def specialist_id(self) -> str:
        return "tools"

    @property
    def description(self) -> str:
        return (
            "Executes domain-specific tools: file operations, system info, "
            "engineering analysis, data processing, and all 132 registered "
            "tool modules."
        )

    @property
    def capabilities(self) -> set[str]:
        return {
            "tool_execution",
            "file_operations",
            "system_info",
            "data_processing",
            "engineering",
            "automation",
            "filesystem",
            "shell",
            "project_stats",
        }

    async def _execute_impl(
        self,
        contract: DelegationContract,
        token: CapabilityToken,
        prompt: str,
        conversation_context: list[dict[str, Any]],
        memory_context: str,
    ) -> AsyncIterator[dict[str, Any]]:
        provider = str(getattr(getattr(self.llm, "config", None), "provider", "") or "").strip().lower()
        if provider == "codex" and hasattr(self.llm, "stream_chat"):
            direct_messages = [
                {
                    "role": "system",
                    "content": (
                        "You are Thomas's tool execution specialist. "
                        "Use available tools when needed to complete the user's request. "
                        "Return the final answer in plain text only."
                    ),
                }
            ]
            if memory_context:
                direct_messages.append({"role": "system", "content": f"Context:\n{memory_context}"})
            for msg in conversation_context:
                if msg.get("role") == "system":
                    continue
                direct_messages.append(msg)
            direct_messages.append({"role": "user", "content": prompt})

            streamed_parts: list[str] = []
            tool_results = 0
            async for event in self.llm.stream_chat(
                messages=direct_messages,
                tools=[{"type": "function", "function": {"name": "codex_tools_enabled"}}],
            ):
                event_type = str(getattr(event, "type", "") or "")
                data = getattr(event, "data", {}) or {}
                if event_type == "token":
                    token_text = str(data.get("text", "") or "")
                    if token_text:
                        streamed_parts.append(token_text)
                        yield {"type": "text", "text": token_text}
                elif event_type == "tool_call_start":
                    yield {
                        "type": "tool_start",
                        "name": str(data.get("name", "") or "tool"),
                        "id": str(data.get("id", "") or ""),
                        "args": {},
                    }
                elif event_type == "tool_call_end":
                    tool_results += 1
                    yield {
                        "type": "tool_result",
                        "name": str(data.get("name", "") or "tool"),
                        "id": str(data.get("id", "") or ""),
                        "ok": True,
                        "result": str(data.get("output", "") or ""),
                        "ms": 0,
                    }
                elif event_type == "error":
                    yield {"type": "error", "error": str(data.get("error") or "Tool execution failed")}
                    return
                elif event_type == "done":
                    break

            response = "".join(streamed_parts).strip()
            if not response:
                yield {"type": "error", "error": "Tool specialist returned an empty response"}
                return

            yield {"type": "done", "content": response, "iterations": 1, "tool_calls": tool_results}
            return

        yield {
            "type": "thinking",
            "text": "Determining which tools to use...",
            "phase": "tool_selection",
        }

        # Ask LLM what tools to call
        available_tools = "general tools"
        if self.tools and hasattr(self.tools, "list_tools"):
            try:
                tool_list = self.tools.list_tools()
                if tool_list:
                    available_tools = ", ".join(t[:30] for t in tool_list[:50])
            except Exception:
                pass

        system = (
            "You are Thomas's tool execution specialist. Determine which tools "
            "to call for the user's request. Respond with a JSON array of tool "
            "calls, each with 'tool' and 'args' keys. If no tools are needed, "
            "respond with an empty array [].\n\n"
            f"Available tools: {available_tools}\n\n"
        )
        if memory_context:
            system += f"Context:\n{memory_context}\n\n"

        messages = [{"role": "system", "content": system}]
        messages.append({"role": "user", "content": prompt})

        try:
            plan = await self._call_llm(messages, max_tokens=1_000)
            tool_calls = json.loads(plan) if plan.strip().startswith("[") else []
        except (json.JSONDecodeError, Exception):
            tool_calls = []

        results = []
        for tc in tool_calls[:5]:  # max 5 tools per turn
            tool_name = tc.get("tool", "")
            tool_args = tc.get("args", {})

            async for event in self._run_tool(tool_name, tool_args, token):
                yield event
                if event.get("type") == "tool_result":
                    results.append(event)

        # Synthesise tool results into response
        if results:
            result_text = "\n".join(f"- {r.get('name', '?')}: {r.get('result', '')[:500]}" for r in results)
            synthesis_messages = [
                {"role": "system", "content": "Summarise these tool results for the user."},
                {"role": "user", "content": f"User asked: {prompt}\n\nTool results:\n{result_text}"},
            ]
            response = await self._call_llm(synthesis_messages, max_tokens=2_000)
        else:
            # No tools needed — respond directly
            messages_direct = [
                {"role": "system", "content": "You are Thomas's assistant. Respond helpfully."},
            ]
            # FIX (2026-03-18): Include full conversation, filter system prompts.
            for msg in conversation_context:
                if msg.get("role") == "system":
                    continue
                messages_direct.append(msg)
            messages_direct.append({"role": "user", "content": prompt})
            response = await self._call_llm(messages_direct, max_tokens=2_000)

        yield {"type": "text", "text": response}
        yield {"type": "done", "content": response, "iterations": 1, "tool_calls": len(results)}
