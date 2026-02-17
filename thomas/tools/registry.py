"""Dynamic tool registry with categories and OpenAI spec generation."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from thomas.tools.base import Tool, ToolResult, ToolSpec

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
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if not tool.name:
            raise ValueError("Tool must have a name")
        if tool.name in self._tools:
            log.warning("Overwriting tool: %s", tool.name)
        self._tools[tool.name] = tool
        log.debug("Registered tool: %s [%s]", tool.name, tool.category)

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def list_tools(self, category: Optional[str] = None) -> List[Tool]:
        tools = list(self._tools.values())
        if category:
            tools = [t for t in tools if t.category == category]
        return sorted(tools, key=lambda t: t.name)

    def list_categories(self) -> List[str]:
        cats = sorted(set(t.category for t in self._tools.values()))
        return cats

    def get_openai_specs(
        self, category: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Generate OpenAI function-calling tool specs."""
        tools = self.list_tools(category)
        return [t.get_spec().to_openai() for t in tools]

    async def execute(self, name: str, args: Dict[str, Any]) -> ToolResult:
        """Execute a tool by name with error handling."""
        tool = self.get(name)
        if tool is None:
            return ToolResult(
                ok=False,
                error=f"Unknown tool: {name}. Available: {', '.join(self._tools.keys())}",
            )
        return await tool.safe_execute(args)

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
