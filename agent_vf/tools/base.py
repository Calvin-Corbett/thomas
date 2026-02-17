from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, List

@dataclass
class Tool:
    name: str
    description: str
    schema: Dict[str, Any]
    handler: Callable[[Dict[str, Any]], Dict[str, Any]]

class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def list(self) -> List[Tool]:
        return list(self._tools.values())

    def openai_tool_specs(self):
        specs = []
        for t in self._tools.values():
            specs.append({
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.schema,
                }
            })
        return specs
