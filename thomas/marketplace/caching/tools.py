"""Tools for Caching module.

Provides tools for cache management, statistics, and configuration.
"""

from typing import Any

from thomas import caching
from thomas.tools.base import Tool, ToolResult


class CacheManagementTool(Tool):
    """Manage cache instances and operations."""

    name = "cache_management"
    category = "caching"
    description = "Create and configure LRU, LFU, TTL, and multi-tier caches"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create_lru", "create_lfu", "create_ttl", "create_multi_tier"],
                "description": "Cache type to create",
            },
            "max_size": {"type": "integer", "description": "Maximum cache size (default: 1000)"},
            "ttl_seconds": {"type": "number", "description": "Time-to-live in seconds for TTL cache"},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")
            max_size = int(args.get("max_size", 1000))

            if action == "create_lru":
                caching.LRUCache(max_size=max_size)
                return ToolResult(ok=True, data={"status": "cache_created", "type": "LRU", "max_size": max_size})

            elif action == "create_lfu":
                caching.LFUCache(max_size=max_size)
                return ToolResult(ok=True, data={"status": "cache_created", "type": "LFU", "max_size": max_size})

            elif action == "create_ttl":
                ttl_seconds = float(args.get("ttl_seconds", 3600))
                caching.TTLCache(max_size=max_size, ttl_seconds=ttl_seconds)
                return ToolResult(
                    ok=True,
                    data={"status": "cache_created", "type": "TTL", "max_size": max_size, "ttl_seconds": ttl_seconds},
                )

            elif action == "create_multi_tier":
                caching.MultiTierCache()
                return ToolResult(ok=True, data={"status": "cache_created", "type": "MultiTier"})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class InvalidationTool(Tool):
    """Manage cache invalidation strategies."""

    name = "cache_invalidation"
    category = "caching"
    description = "Configure tag-based, pattern-based, and cascading cache invalidation"
    parameters = {
        "type": "object",
        "properties": {
            "strategy": {
                "type": "string",
                "enum": ["tag_based", "pattern_based", "cascading"],
                "description": "Invalidation strategy type",
            }
        },
        "required": ["strategy"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            strategy = args.get("strategy", "")

            if strategy == "tag_based":
                caching.TagBasedInvalidation()
                return ToolResult(ok=True, data={"status": "invalidator_created", "strategy": "tag_based"})

            elif strategy == "pattern_based":
                caching.PatternBasedInvalidation()
                return ToolResult(ok=True, data={"status": "invalidator_created", "strategy": "pattern_based"})

            elif strategy == "cascading":
                caching.CascadingInvalidation()
                return ToolResult(ok=True, data={"status": "invalidator_created", "strategy": "cascading"})

            else:
                return ToolResult(ok=False, error=f"Unknown strategy: {strategy}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class WarmingTool(Tool):
    """Manage cache warming strategies."""

    name = "cache_warming"
    category = "caching"
    description = "Configure and manage cache warming strategies"
    parameters = {
        "type": "object",
        "properties": {
            "strategy": {
                "type": "string",
                "enum": ["batch", "scheduled", "pattern_based"],
                "description": "Warming strategy type",
            }
        },
        "required": ["strategy"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            strategy = args.get("strategy", "")

            if strategy == "batch":
                caching.BatchWarmer()
                return ToolResult(ok=True, data={"status": "warmer_created", "strategy": "batch"})

            elif strategy == "scheduled":
                caching.ScheduledWarmer()
                return ToolResult(ok=True, data={"status": "warmer_created", "strategy": "scheduled"})

            elif strategy == "pattern_based":
                caching.PatternBasedWarmer()
                return ToolResult(ok=True, data={"status": "warmer_created", "strategy": "pattern_based"})

            else:
                return ToolResult(ok=False, error=f"Unknown strategy: {strategy}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_caching_tools(registry):
    """Register all caching tools."""
    registry.register(CacheManagementTool())
    registry.register(InvalidationTool())
    registry.register(WarmingTool())
