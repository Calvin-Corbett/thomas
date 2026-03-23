"""Tools for CDN module.

Provides tools for edge caching, purging, and distribution management.
"""

from typing import Any

from thomas.marketplace.cdn import core
from thomas.tools.base import Tool, ToolResult


class EdgeCacheTool(Tool):
    """Manage edge cache locations."""

    name = "cdn_edge_cache"
    category = "cdn"
    description = "Manage edge cache locations and caching"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add_location", "list_locations", "get_location_stats"],
                "description": "Cache management action",
            },
            "region": {"type": "string", "description": "Region for edge location"},
            "city": {"type": "string", "description": "City for edge location"},
            "location_id": {"type": "string", "description": "Edge location ID"},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.cdn = core.CDN()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "add_location":
                region = args.get("region", "us-west")
                city = args.get("city", "unknown")
                location = self.cdn.add_edge_location(region, city)
                return ToolResult(ok=True, data={"location_id": location.id, "region": region, "city": city})

            elif action == "list_locations":
                locations = [
                    {"id": loc.id, "region": loc.region, "city": loc.city} for loc in self.cdn.edge_locations.values()
                ]
                return ToolResult(ok=True, data={"locations": locations})

            elif action == "get_location_stats":
                location_id = args.get("location_id", "")
                if not location_id:
                    return ToolResult(ok=False, error="location_id required")

                stats = self.cdn.get_location_stats(location_id)
                if stats:
                    return ToolResult(ok=True, data=stats)
                else:
                    return ToolResult(ok=False, error=f"Location not found: {location_id}")

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class CachePurgeTool(Tool):
    """Purge cached content."""

    name = "cdn_purge"
    category = "cdn"
    description = "Purge cache entries by pattern or location"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["purge_pattern", "purge_location", "get_purge_history"],
                "description": "Purge action",
            },
            "pattern": {"type": "string", "description": "URL pattern to purge"},
            "location_id": {"type": "string", "description": "Edge location ID"},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.cdn = core.CDN()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "purge_pattern":
                pattern = args.get("pattern", "")
                purged = self.cdn.purge_cache(pattern=pattern)
                return ToolResult(ok=True, data={"purged_entries": purged, "pattern": pattern})

            elif action == "purge_location":
                location_id = args.get("location_id", "")
                purged = self.cdn.purge_cache(edge_location_id=location_id)
                return ToolResult(ok=True, data={"purged_entries": purged, "location": location_id})

            elif action == "get_purge_history":
                history = self.cdn.purge_history[-10:]
                return ToolResult(ok=True, data={"purge_history": history})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class OriginShieldTool(Tool):
    """Manage origin shield and origin servers."""

    name = "cdn_origin_shield"
    category = "cdn"
    description = "Manage origin shield and origin servers"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["enable_shield", "disable_shield", "register_origin", "list_origins"],
                "description": "Origin shield action",
            },
            "origin_name": {"type": "string", "description": "Origin server name"},
            "origin_url": {"type": "string", "description": "Origin server URL"},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.cdn = core.CDN()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "enable_shield":
                self.cdn.enable_origin_shield(True)
                return ToolResult(ok=True, data={"origin_shield": "enabled"})

            elif action == "disable_shield":
                self.cdn.enable_origin_shield(False)
                return ToolResult(ok=True, data={"origin_shield": "disabled"})

            elif action == "register_origin":
                origin_name = args.get("origin_name", "")
                origin_url = args.get("origin_url", "")

                if not origin_name or not origin_url:
                    return ToolResult(ok=False, error="origin_name and origin_url required")

                self.cdn.register_origin_server(origin_name, origin_url)
                return ToolResult(ok=True, data={"origin_name": origin_name, "origin_url": origin_url})

            elif action == "list_origins":
                origins = list(self.cdn.origin_servers.items())
                return ToolResult(ok=True, data={"origins": origins})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class CDNMonitoringTool(Tool):
    """Monitor CDN performance and statistics."""

    name = "cdn_monitor"
    category = "cdn"
    description = "Get CDN statistics and performance metrics"
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["get_stats", "get_health"], "description": "Monitoring action"}
        },
        "required": ["action"],
    }

    def __init__(self):
        self.cdn = core.CDN()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "get_stats":
                stats = self.cdn.get_cdn_stats()
                return ToolResult(ok=True, data=stats)

            elif action == "get_health":
                stats = self.cdn.get_cdn_stats()
                health = {
                    "status": "healthy" if stats["hit_ratio"] > 0.5 else "degraded",
                    "hit_ratio": stats["hit_ratio"],
                    "edge_locations": stats["edge_locations"],
                    "origin_servers": stats["origin_servers"],
                }
                return ToolResult(ok=True, data=health)

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_cdn_tools(registry):
    """Register all CDN tools."""
    registry.register(EdgeCacheTool())
    registry.register(CachePurgeTool())
    registry.register(OriginShieldTool())
    registry.register(CDNMonitoringTool())
