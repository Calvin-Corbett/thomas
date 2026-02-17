"""Tool base class and result types for Thomas."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class ToolResult:
    """Result from a tool execution."""

    ok: bool
    data: Any = None
    error: Optional[str] = None
    duration_ms: float = 0.0

    def to_content(self, max_len: int = 50_000) -> str:
        """Serialize to a string for inclusion in LLM messages."""
        if not self.ok:
            return json.dumps({"ok": False, "error": self.error or "unknown error"})
        if isinstance(self.data, str):
            text = self.data
        else:
            text = json.dumps(self.data, ensure_ascii=False, default=str)
        if len(text) > max_len:
            text = text[:max_len - 50] + f"\n... (truncated, {len(text)} chars total)"
        return text


@dataclass
class ToolSpec:
    """OpenAI-compatible tool specification for sending to LLMs."""

    name: str
    description: str
    parameters: Dict[str, Any]

    def to_openai(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class Tool:
    """Base class for Thomas tools.

    Subclass and implement execute() to create a tool.
    """

    name: str = ""
    category: str = "general"
    description: str = ""
    parameters: Dict[str, Any] = {}

    async def execute(self, args: Dict[str, Any]) -> ToolResult:
        raise NotImplementedError

    def get_spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
        )

    async def safe_execute(self, args: Dict[str, Any]) -> ToolResult:
        """Execute with error handling and timing."""
        start = time.monotonic()
        try:
            result = await self.execute(args)
            result.duration_ms = (time.monotonic() - start) * 1000
            return result
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            return ToolResult(
                ok=False,
                error=f"{type(e).__name__}: {e}",
                duration_ms=duration,
            )
