"""Tool Specialist - executes domain tools from Thomas's 132 modules.

This specialist handles tasks that require invoking Thomas's domain
tools (bioinformatics, CAD, telecom, blockchain, IoT, robotics,
climate, energy, gaming, music, engineering, filesystem, etc.).

It uses the LLM to decide which tools to call, then executes them
with capability-token permission checking.
"""

from __future__ import annotations

import contextlib
import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from thomas.marketplace.orchestrator.protocol import CapabilityToken, DelegationContract
from thomas.marketplace.specialists.base import BaseSpecialist
from thomas.marketplace.specialists.tools_direct_runtime import run_direct_fast_path
from thomas.marketplace.specialists.tools_fast_path import (
    _create_weekday_local_reminder,
    _extract_main_headline_text,
    _extract_strict_output,
    _fetch_browser_headline,
    _fetch_browser_main_text,
    _fetch_browser_title,
    _find_named_file_on_desktop,
    _launch_local_application,
    _normalize_requested_content,
    _parse_clock_time,
    _resolve_app_launch_target,
    _should_force_tool_first,
    _should_require_output_only,
)
from thomas.tools.browser import BrowserClickTool, BrowserOpenTool

log = logging.getLogger(__name__)

__all__ = [
    "ToolSpecialist",
    "_extract_main_headline_text",
    "_extract_strict_output",
    "_fetch_browser_headline",
    "_fetch_browser_main_text",
    "_fetch_browser_title",
    "_find_named_file_on_desktop",
    "_create_weekday_local_reminder",
    "_launch_local_application",
    "_normalize_requested_content",
    "_parse_clock_time",
    "_resolve_app_launch_target",
    "_should_force_tool_first",
    "_should_require_output_only",
    "BrowserClickTool",
    "BrowserOpenTool",
    "Path",
]

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

    async def _run_direct_fast_path(
        self,
        prompt: str,
        token: CapabilityToken,
        conversation_context: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        _ = conversation_context
        async for event in run_direct_fast_path(prompt, token):
            yield event

    async def _execute_impl(
        self,
        contract: DelegationContract,
        token: CapabilityToken,
        prompt: str,
        conversation_context: list[dict[str, Any]],
        memory_context: str,
    ) -> AsyncIterator[dict[str, Any]]:
        async for direct_event in run_direct_fast_path(prompt, token):
            yield direct_event
            if direct_event.get("type") == "done":
                return
            if direct_event.get("type") == "error":
                return

        provider = str(getattr(getattr(self.llm, "config", None), "provider", "") or "").strip().lower()
        if provider == "codex" and hasattr(self.llm, "stream_chat"):
            force_tool_first = _should_force_tool_first(prompt)
            strict_output_only = _should_require_output_only(prompt)
            llm_config = getattr(self.llm, "config", None)
            original_effort = getattr(llm_config, "reasoning_effort", None) if llm_config is not None else None
            if force_tool_first and llm_config is not None:
                with contextlib.suppress(AttributeError, TypeError):
                    llm_config.reasoning_effort = "low"
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
            if force_tool_first:
                direct_messages.append(
                    {
                        "role": "system",
                        "content": (
                            "This request explicitly asks for filesystem or tool execution. "
                            "If a tool is needed, start with the tool call immediately. "
                            "Do not narrate your plan or emit user-visible text before the first tool call. "
                            "If the prompt gives an explicit absolute path, use that path directly. "
                            "Do not list directories, inspect the repo, or probe the filesystem first unless the user asked for that. "
                            "For broader build, repair, or project requests, prefer marketplace skills, plugins, and existing tool context "
                            "instead of inventing ad hoc project scaffolds or hardcoded flows. "
                            "If the prompt explicitly says to create or overwrite a file with given contents, write it directly. "
                            "After the required tool calls finish, give a short final answer only."
                        ),
                    }
                )
            if strict_output_only:
                direct_messages.append(
                    {
                        "role": "system",
                        "content": (
                            "The user requested a strict output format. "
                            "Keep tool progress in tool events only. "
                            "Do not emit user-visible narration or status updates. "
                            "After all needed tool calls finish, return only the requested final output."
                        ),
                    }
                )
            if memory_context:
                direct_messages.append({"role": "system", "content": f"Context:\n{memory_context}"})
            context_messages = [msg for msg in conversation_context if msg.get("role") != "system"]
            if force_tool_first:
                context_messages = context_messages[-2:]
            for msg in context_messages:
                if msg.get("role") == "system":
                    continue
                direct_messages.append(msg)
            direct_messages.append({"role": "user", "content": prompt})

            try:
                streamed_parts: list[str] = []
                tool_results = 0
                tool_outputs: list[str] = []
                pre_tool_parts: list[str] = []
                tool_started = False
                async for event in self.llm.stream_chat(
                    messages=direct_messages,
                    tools=[{"type": "function", "function": {"name": "codex_tools_enabled"}}],
                ):
                    event_type = str(getattr(event, "type", "") or "")
                    data = getattr(event, "data", {}) or {}
                    if event_type == "token":
                        token_text = str(data.get("text", "") or "")
                        if token_text:
                            if strict_output_only:
                                streamed_parts.append(token_text)
                            elif force_tool_first and not tool_started:
                                pre_tool_parts.append(token_text)
                            else:
                                streamed_parts.append(token_text)
                                yield {"type": "text", "text": token_text}
                    elif event_type == "tool_call_start":
                        tool_started = True
                        pre_tool_parts.clear()
                        yield {
                            "type": "tool_start",
                            "name": str(data.get("name", "") or "tool"),
                            "id": str(data.get("id", "") or ""),
                            "args": {},
                        }
                    elif event_type == "tool_call_end":
                        tool_results += 1
                        tool_outputs.append(str(data.get("output", "") or ""))
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

                if force_tool_first and not strict_output_only and not tool_started and pre_tool_parts:
                    for token_text in pre_tool_parts:
                        streamed_parts.append(token_text)
                        yield {"type": "text", "text": token_text}

                response = "".join(streamed_parts).strip()
                if strict_output_only:
                    response = _extract_strict_output(prompt, response, tool_outputs)
                    if response:
                        yield {"type": "text", "text": response}
                if not response:
                    yield {"type": "error", "error": "Tool specialist returned an empty response"}
                    return

                yield {"type": "done", "content": response, "iterations": 1, "tool_calls": tool_results}
                return
            finally:
                if force_tool_first and llm_config is not None:
                    with contextlib.suppress(AttributeError, TypeError):
                        llm_config.reasoning_effort = original_effort

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
            except (AttributeError, TypeError, ValueError):
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
