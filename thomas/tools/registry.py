"""Dynamic tool registry with categories and OpenAI spec generation."""

from __future__ import annotations

import logging
import re
from typing import Any

from thomas.tools.base import Tool, ToolResult

log = logging.getLogger(__name__)


class ToolRegistry:
    """Registry for tool discovery, lookup, and spec generation.

    Supports:
    - Register/unregister tools at runtime
    - Lookup by name
    - List by category
    - Generate OpenAI-compatible tool specs for LLM calls
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if not tool.name:
            raise ValueError("Tool must have a name")
        if tool.name in self._tools:
            log.warning("Overwriting tool: %s", tool.name)
        self._tools[tool.name] = tool
        log.debug("Registered tool: %s [%s]", tool.name, tool.category)

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        tool = self._tools.get(name)
        if tool is not None:
            return tool
        resolved = self._resolve_tool_name(name)
        if resolved is None:
            return None
        return self._tools.get(resolved)

    @staticmethod
    def _canonical_name(name: str) -> str:
        return re.sub(r"[^a-z0-9]+", ".", str(name or "").strip().lower()).strip(".")

    def _resolve_tool_name(self, name: str) -> str | None:
        raw = str(name or "").strip()
        if not raw or not self._tools:
            return None

        # Case-insensitive exact match.
        lowered = raw.lower()
        case_matches = [tool_name for tool_name in self._tools if tool_name.lower() == lowered]
        if len(case_matches) == 1:
            return case_matches[0]

        # Common namespacing wrappers seen in model outputs.
        for prefix in ("functions.", "function.", "tool.", "tools.", "mcp.", "mcp__"):
            if lowered.startswith(prefix):
                trimmed = raw[len(prefix) :].strip()
                if trimmed in self._tools:
                    return trimmed
                trimmed_matches = [tool_name for tool_name in self._tools if tool_name.lower() == trimmed.lower()]
                if len(trimmed_matches) == 1:
                    return trimmed_matches[0]

        variants = {
            raw,
            raw.replace("_", "."),
            raw.replace("-", "."),
            raw.replace(".", "_"),
            raw.replace("-", "_"),
            raw.replace(".", "-"),
            raw.replace("_", "-"),
        }
        for variant in variants:
            if variant in self._tools:
                return variant

        target = self._canonical_name(raw)
        canonical_matches = [tool_name for tool_name in self._tools if self._canonical_name(tool_name) == target]
        if len(canonical_matches) == 1:
            return canonical_matches[0]

        # Fallback: match by last 2-3 canonical segments, e.g. functions.fs.read_file.
        segments = [seg for seg in target.split(".") if seg]
        for tail_len in (3, 2):
            if len(segments) < tail_len:
                continue
            tail = ".".join(segments[-tail_len:])
            tail_matches = [tool_name for tool_name in self._tools if self._canonical_name(tool_name) == tail]
            if len(tail_matches) == 1:
                return tail_matches[0]

        return None

    def list_tools(self, category: str | None = None) -> list[Tool]:
        tools = list(self._tools.values())
        if category:
            tools = [t for t in tools if t.category == category]
        return sorted(tools, key=lambda t: t.name)

    def list_categories(self) -> list[str]:
        cats = sorted(set(t.category for t in self._tools.values()))
        return cats

    def search(self, query: str, limit: int = 10) -> list[Tool]:
        """Search tools by semantic keyword overlap."""
        if not query:
            return []

        q_tokens = set(re.findall(r"\w+", query.lower()))
        scores: list[tuple[float, Tool]] = []

        for tool in self._tools.values():
            score = 0.0
            # Exact name match (high)
            if query.lower() in tool.name.lower():
                score += 10.0

            # Token overlap
            t_name_tokens = set(re.findall(r"\w+", tool.name.lower()))
            score += len(q_tokens & t_name_tokens) * 3.0

            if tool.description:
                t_desc_tokens = set(re.findall(r"\w+", tool.description.lower()))
                score += len(q_tokens & t_desc_tokens) * 1.0

            if score > 0:
                scores.append((score, tool))

        # Sort by score desc, then name
        scores.sort(key=lambda x: (-x[0], x[1].name))
        return [s[1] for s in scores[:limit]]

    def get_openai_specs(self, category: str | None = None) -> list[dict[str, Any]]:
        """Generate OpenAI function-calling tool specs."""
        tools = self.list_tools(category)
        return [t.get_spec().to_openai() for t in tools]

    async def execute(self, name: str, args: dict[str, Any]) -> ToolResult:
        """Execute a tool by name with error handling."""
        tool = self.get(name)
        if tool is None:
            return ToolResult(
                ok=False,
                error=f"Unknown tool: {name}. Available: {', '.join(self._tools.keys())}",
            )
        if tool.name != name:
            log.debug("Resolved tool alias '%s' -> '%s'", name, tool.name)
        return await tool.safe_execute(args)

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
