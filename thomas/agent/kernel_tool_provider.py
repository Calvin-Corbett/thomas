"""Compose mounted tools with the tools a particular turn already owns."""

from __future__ import annotations

from typing import Any
from weakref import WeakSet

from thomas.tools.registry import ToolRegistry


class DefaultTools(ToolRegistry):
    """Kernel provider for the server registry; a turn keeps its own registry."""

    def __init__(self, tools: Any) -> None:
        super().__init__()
        self.tools = tools

    def list_tools(self, category: str | None = None) -> list[Any]:
        return self.tools.list_tools(category)

    def get(self, name: str) -> Any:
        return self.tools.get(name)

    async def execute(self, name: str, args: dict[str, Any]) -> Any:
        return await self.tools.execute(name, args)

    def for_turn(self, base: Any) -> Any:
        return base

    def list_categories(self) -> list[str]:
        return self.tools.list_categories()

    def search(self, query: str, limit: int = 10) -> list[Any]:
        return self.tools.search(query, limit)

    def _resolve_tool_name(self, name: str) -> str | None:
        return self.tools._resolve_tool_name(name)

    def __len__(self) -> int:
        return len(self.tools)

    def __contains__(self, name: str) -> bool:
        return name in self.tools


class MountedTools(ToolRegistry):
    """A registry view that retains the turn's own tools and mounted additions."""

    def __init__(self, base: Any, additions: list[Any]) -> None:
        super().__init__()
        self.base = base
        self.additions = additions
        self.active = True
        self.views: WeakSet[MountedToolView] = WeakSet()

    def withdraw(self) -> None:
        self.active = False
        for view in self.views:
            view.withdraw(self.additions)

    def for_turn(self, base: Any, *, allow_new: bool = False) -> Any:
        if isinstance(self.base, MountedTools):
            previous = self.base.for_turn(base, allow_new=allow_new)
        else:
            previous = self.base.for_turn(base) if hasattr(self.base, "for_turn") else base
        if not self.active or previous is None:
            return previous
        # Never put an unfiltered view outside a restricted turn. The worker
        # explicitly opts in *before* it applies deny lists and policy wrappers.
        if isinstance(previous, MountedToolView):
            current = previous
            while isinstance(current, MountedToolView):
                if current.mount is self:
                    return previous
                current = current.base
            view = MountedToolView(previous, self)
        elif type(previous) is ToolRegistry and (allow_new or self._is_server_registry(previous)):
            view = MountedToolView(previous, self)
        else:
            return previous
        self.views.add(view)
        return view

    def _is_server_registry(self, base: Any) -> bool:
        provider = self
        while isinstance(provider, MountedTools):
            provider = provider.base
        return isinstance(provider, DefaultTools) and base is provider.tools

    def list_tools(self, category: str | None = None) -> list[Any]:
        return self._registry().list_tools(category)

    def _registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        for tool in self.base.list_tools():
            registry.register(tool)
        if self.active:
            for tool in self.additions:
                registry.register(tool)
        return registry

    def list_categories(self) -> list[str]:
        return self._registry().list_categories()

    def search(self, query: str, limit: int = 10) -> list[Any]:
        return self._registry().search(query, limit)

    def _resolve_tool_name(self, name: str) -> str | None:
        return self._registry()._resolve_tool_name(name)

    def get(self, name: str) -> Any:
        return self._registry().get(name)

    async def execute(self, name: str, args: dict[str, Any]) -> Any:
        tool = self.get(name)
        if tool is None:
            from thomas.tools.base import ToolResult

            return ToolResult(ok=False, error=f"Unknown tool: {name}")
        return await tool.safe_execute(args)

    def __len__(self) -> int:
        return len(self.list_tools())

    def __contains__(self, name: str) -> bool:
        return self.get(name) is not None


class MountedToolView(ToolRegistry):
    """Live turn view: a disposed mount cannot keep executing through old turns."""

    def __init__(self, base: Any, mount: MountedTools) -> None:
        super().__init__()
        self.base = base
        self.mount = mount
        self.denied: set[str] = set()
        for tool in base.list_tools():
            super().register(tool)
        for tool in mount.additions:
            super().register(tool)
        self._local_tools: dict[str, Any] = {}

    def register(self, tool: Any) -> None:
        super().register(tool)
        self._local_tools[tool.name] = tool

    def withdraw(self, tools: list[Any]) -> None:
        for tool in tools:
            current = self._tools.get(tool.name)
            if current is tool:
                super().unregister(tool.name)
                previous = self.base.get(tool.name)
                if previous is not None and tool.name not in self.denied:
                    super().register(previous)

    def unregister(self, name: str) -> None:
        resolved = self._resolve_tool_name(name) or name
        self.denied.add(resolved)
        self._local_tools.pop(resolved, None)
        super().unregister(resolved)

    def list_tools(self, category: str | None = None) -> list[Any]:
        tools = {tool.name: tool for tool in self.base.list_tools(category)}
        if self.mount.active:
            tools.update(
                (tool.name, tool) for tool in self.mount.additions if category is None or tool.category == category
            )
        tools.update(
            (name, tool) for name, tool in self._local_tools.items() if category is None or tool.category == category
        )
        return sorted((tool for name, tool in tools.items() if name not in self.denied), key=lambda tool: tool.name)

    def _registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        for tool in self.list_tools():
            registry.register(tool)
        return registry

    def list_categories(self) -> list[str]:
        return self._registry().list_categories()

    def search(self, query: str, limit: int = 10) -> list[Any]:
        return self._registry().search(query, limit)

    def _resolve_tool_name(self, name: str) -> str | None:
        return self._registry()._resolve_tool_name(name)

    def get(self, name: str) -> Any:
        return self._registry().get(name)

    async def execute(self, name: str, args: dict[str, Any]) -> Any:
        tool = self.get(name)
        if tool is None:
            from thomas.tools.base import ToolResult

            return ToolResult(ok=False, error=f"Unknown tool: {name}")
        return await tool.safe_execute(args)

    def __len__(self) -> int:
        return len(self.list_tools())

    def __contains__(self, name: str) -> bool:
        return self.get(name) is not None
