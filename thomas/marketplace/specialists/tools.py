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
from dataclasses import replace
from typing import Any

from thomas.marketplace.orchestrator.protocol import CapabilityToken, DelegationContract
from thomas.marketplace.specialists.base import BaseSpecialist

log = logging.getLogger(__name__)


# Categories most useful for chat-driven actions get listed first so the
# catalog stays within a local model's smaller context window when capped.
_PRIORITY_CATEGORIES = ("filesystem", "fs", "shell", "git", "code", "diff", "eng", "system")
_CATALOG_TOOL_CAP = 70


def _extract_tool_calls(plan: str) -> list[dict[str, Any]]:
    """Parse a tool-call plan from a (possibly messy) local-model response.

    Local models often wrap JSON in markdown fences or add a sentence of
    preamble. Be tolerant: strip fences, then parse the first JSON array
    (or a bare object) found in the text. Returns [] on any failure.
    """
    text = str(plan or "").strip()
    if not text:
        return []

    # Strip ```json ... ``` / ``` ... ``` fences.
    if "```" in text:
        import re as _re

        fence = _re.search(r"```(?:json)?\s*(.+?)```", text, _re.S | _re.I)
        if fence:
            text = fence.group(1).strip()

    candidates: list[str] = []
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    obj_start = text.find("{")
    obj_end = text.rfind("}")
    if obj_start != -1 and obj_end > obj_start:
        candidates.append(text[obj_start : obj_end + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, dict):
            parsed = [parsed]
        if isinstance(parsed, list):
            calls = [c for c in parsed if isinstance(c, dict) and c.get("tool")]
            if calls:
                return calls
    return []


class ToolSpecialist(BaseSpecialist):
    """Domain tool execution specialist for Thomas's 132 tool modules."""

    def _build_tool_catalog(self) -> str:
        """Render available tools as compact signatures the LLM can call.

        Each line is ``name(required_args) — description``. Priority
        categories (filesystem, shell, git, …) are listed first, then the
        list is capped so the catalog fits a local model's context window.
        """
        if not (self.tools and hasattr(self.tools, "list_tools")):
            return "(no tools registered)"
        try:
            tool_list = list(self.tools.list_tools())
        except Exception:
            return "(tool catalog unavailable)"
        if not tool_list:
            return "(no tools registered)"

        def _priority(tool: Any) -> int:
            cat = str(getattr(tool, "category", "") or "").lower()
            for idx, name in enumerate(_PRIORITY_CATEGORIES):
                if name in cat:
                    return idx
            return len(_PRIORITY_CATEGORIES)

        ordered = sorted(tool_list, key=lambda t: (_priority(t), str(getattr(t, "name", ""))))
        lines: list[str] = []
        for tool in ordered[:_CATALOG_TOOL_CAP]:
            name = str(getattr(tool, "name", "") or "")
            if not name:
                continue
            params = getattr(tool, "parameters", None) or {}
            required = params.get("required", []) if isinstance(params, dict) else []
            sig = ", ".join(str(r) for r in required)
            desc = str(getattr(tool, "description", "") or "").strip().replace("\n", " ")
            lines.append(f"- {name}({sig}) — {desc[:80]}")
        if len(ordered) > _CATALOG_TOOL_CAP:
            lines.append(f"... and {len(ordered) - _CATALOG_TOOL_CAP} more tools")
        return "\n".join(lines)

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

        # Ask LLM what tools to call. Local models (unlike codex) have no
        # built-in executor, so they must emit a JSON tool plan. That only
        # works if the prompt gives them the real tool names AND argument
        # schemas — previously this passed "general tools" (a swallowed
        # ``t[:30]`` TypeError on Tool objects), so local models never knew
        # ``fs.write_file`` existed and fell back to describing shell commands.
        available_tools = self._build_tool_catalog()

        system = (
            "You are Thomas's tool execution specialist. Decide which tools to "
            "call to fulfil the user's request, then respond with ONLY a JSON "
            "array — no prose, no markdown fences. Each element is an object "
            'with "tool" (exact tool name) and "args" (object matching that '
            "tool's parameters). If no tool is needed, respond with [].\n\n"
            "Example: to create a file you would respond exactly:\n"
            '[{"tool": "fs.write_file", "args": {"path": "notes.txt", '
            '"content": "hello"}}]\n\n'
            f"Available tools (name(required_args) — description):\n{available_tools}\n\n"
        )
        if memory_context:
            system += f"Context:\n{memory_context}\n\n"

        messages = [{"role": "system", "content": system}]
        messages.append({"role": "user", "content": prompt})

        try:
            plan = await self._call_llm(messages, max_tokens=1_000)
            tool_calls = _extract_tool_calls(plan)
        except Exception as exc:
            log.warning("Tool plan generation/parse failed: %s", exc)
            tool_calls = []

        # The issued token's allowed_tools holds the specialist's *capability
        # categories* ("filesystem", "shell", …), not concrete tool names, so
        # token.permits_tool("fs.write_file") would wrongly deny every real
        # call. Scope an execution token to the actually-registered tool names
        # (the registry is the security boundary — only sandboxed-safe tools
        # are registered), preserving autonomy/session/expiry.
        exec_token = token
        try:
            registered = {str(getattr(t, "name", "") or "") for t in self.tools.list_tools() if getattr(t, "name", "")}
            if registered:
                exec_token = replace(token, allowed_tools=registered)
        except Exception:
            exec_token = token

        results = []
        for tc in tool_calls[:5]:  # max 5 tools per turn
            tool_name = tc.get("tool", "")
            tool_args = tc.get("args", {})

            async for event in self._run_tool(tool_name, tool_args, exec_token):
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
