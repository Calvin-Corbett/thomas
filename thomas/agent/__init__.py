"""Thomas AI Agent Framework

Core agent loop and orchestration subsystems for autonomous AI task execution.

Main exports:
- AgentLoop: Async ReAct agent loop with streaming, parallel tools, and context management
- HooksRegistry: Central registry for agent lifecycle events and integrations
- get_hooks_registry: Get the global hooks registry instance
- integration_hooks: Integration hooks for wiring gap-closing modules into agent loop
"""

from thomas.agent.loop import AgentLoop

try:
    from thomas.agent.hooks_registry import (
        HooksRegistry,
        get_hooks_registry,
        reset_global_registry,
    )
except ModuleNotFoundError:
    # Compatibility fallback for partial checkouts where hooks_registry
    # has been removed/moved but core agent imports still need to work.
    class HooksRegistry:  # type: ignore[no-redef]
        pass

    def get_hooks_registry() -> None:  # type: ignore[no-redef]
        return None

    def reset_global_registry() -> None:  # type: ignore[no-redef]
        return None

__all__ = [
    "AgentLoop",
    "HooksRegistry",
    "get_hooks_registry",
    "reset_global_registry",
]
