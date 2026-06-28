"""Tool Specialist — executes tools from Thomas's registered domain modules.

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

# Tool-name fragments that mark an action as high-risk (irreversible / executes
# arbitrary code / mutates external state). Withheld below Agent-level autonomy so
# the autonomy setting actually gates tool access in the worker path.
_HIGH_RISK_TOOL_HINTS = (
    "shell",
    "exec",
    "run_command",
    "subprocess",
    "bash",
    "powershell",
    "delete",
    "remove",
    "rm_",
    ".rm",
    "destroy",
    "drop",
    "truncate",
    "format",
    "deploy",
    "publish",
    "push",
    "force",
    "write_file",
    "fs.write",
    "overwrite",
    "chmod",
    "kill",
    "terminate",
)


def _is_high_risk_tool(name: str) -> bool:
    low = str(name or "").lower()
    return any(hint in low for hint in _HIGH_RISK_TOOL_HINTS)


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
    """Domain tool execution specialist for Thomas's registered tool modules."""

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
            "engineering analysis, data processing, and registered domain "
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
        yield {
            "type": "thinking",
            "text": "Determining which tools to use...",
            "phase": "tool_selection",
        }

        # Ask LLM what tools to call. Local models have no built-in tool
        # executor, so they must emit a JSON tool plan. That only
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
        #
        # Autonomy gating: the token carries autonomy_level — CONSULT it. Below
        # Agent level (3) the user has not granted hands-off execution, so exclude
        # high-risk tools (shell/exec, destructive filesystem, deploy/push). Without
        # this the per-task autonomy setting was nullified (a low-autonomy task could
        # still run shell + fs-write). See thomas/core/autonomy.
        exec_token = token
        try:
            registered = {str(getattr(t, "name", "") or "") for t in self.tools.list_tools() if getattr(t, "name", "")}
            if registered:
                autonomy_level = int(getattr(token, "autonomy_level", 0) or 0)
                if autonomy_level >= 3:
                    allowed = registered
                else:
                    allowed = {n for n in registered if not _is_high_risk_tool(n)}
                    gated = registered - allowed
                    if gated:
                        yield {
                            "type": "thinking",
                            "text": f"Autonomy level {autonomy_level}: withholding {len(gated)} high-risk tools (shell/destructive/deploy).",
                            "phase": "tool_selection",
                        }
                exec_token = replace(token, allowed_tools=allowed)
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
