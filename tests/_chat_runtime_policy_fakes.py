"""The probe tool the chat runtime policy tests register and inspect.

Shared by tests/test_chat_runtime_policy.py and
tests/test_chat_runtime_policy_tool_actions.py, split along the seam
scripts/forge/seam_finder.py named when the first passed 800 lines.
"""

from __future__ import annotations

from thomas.tools.base import Tool, ToolResult


class _ProbeTool(Tool):
    def __init__(self, name: str) -> None:
        self.name = name
        self.category = name.split(".", 1)[0]
        self.description = "policy probe"
        self.parameters = {"type": "object", "properties": {}}
        self.calls: list[dict] = []

    async def execute(self, args: dict) -> ToolResult:
        self.calls.append(dict(args))
        return ToolResult(ok=True, data="ok")
