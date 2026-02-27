"""Plugin marketplace routes for Thomas.

Provides:
  GET /api/plugins/marketplace - List available plugins with search/filter/sort
  GET /api/plugins/marketplace/{id} - Plugin details
  POST /api/plugins/install - Install a plugin
  POST /api/plugins/uninstall - Uninstall a plugin
  GET /api/plugins/installed - List installed plugins
  POST /api/plugins/toggle - Enable/disable a plugin
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum

from aiohttp import web

log = logging.getLogger(__name__)


class PluginCategory(str, Enum):
    """Plugin categories."""

    ALL = "all"
    TOOLS = "tools"
    INTEGRATIONS = "integrations"
    AGENTS = "agents"
    THEMES = "themes"


class MarketplaceException(Exception):
    """Base exception for marketplace operations."""

    pass


class PluginNotFoundException(MarketplaceException):
    """Plugin not found."""

    pass


class PluginInstallException(MarketplaceException):
    """Plugin installation failed."""

    pass


class PluginCompatibilityException(MarketplaceException):
    """Plugin is not compatible with current Thomas version."""

    pass


@dataclass
class PluginInfo:
    """Plugin information."""

    id: str
    name: str
    author: str
    description: str
    version: str
    rating: float
    install_count: int
    icon_url: str
    category: str
    dependencies: list[str]
    min_version: str
    max_version: str
    homepage_url: str | None = None
    repository_url: str | None = None


@dataclass
class InstalledPlugin:
    """Installed plugin info."""

    id: str
    name: str
    version: str
    enabled: bool
    installed_at: str


class PluginStore:
    """In-memory store of available plugins."""

    # Mock marketplace plugins data
    AVAILABLE_PLUGINS = [
        PluginInfo(
            id="plugin-email",
            name="Email Integration",
            author="Thomas Team",
            description="Advanced email handling with auto-categorization and smart replies",
            version="1.2.0",
            rating=4.8,
            install_count=2341,
            icon_url="/static/icons/email.svg",
            category="integrations",
            dependencies=[],
            min_version="1.0.0",
            max_version="2.0.0",
            homepage_url="https://thomas.ai/plugins/email",
            repository_url="https://github.com/thomas/plugin-email",
        ),
        PluginInfo(
            id="plugin-calendar",
            name="Calendar Assistant",
            author="Thomas Team",
            description="Smart scheduling, meeting prep, and availability management",
            version="1.0.5",
            rating=4.6,
            install_count=1876,
            icon_url="/static/icons/calendar.svg",
            category="tools",
            dependencies=["plugin-email"],
            min_version="1.0.0",
            max_version="2.0.0",
        ),
        PluginInfo(
            id="plugin-code-review",
            name="Code Review Assistant",
            author="Dev Tools Inc",
            description="Automated code review with best practices and security checks",
            version="2.1.3",
            rating=4.9,
            install_count=3421,
            icon_url="/static/icons/code-review.svg",
            category="tools",
            dependencies=[],
            min_version="1.5.0",
            max_version="2.0.0",
        ),
        PluginInfo(
            id="plugin-slack-bot",
            name="Slack Bot Integration",
            author="Slack Partners",
            description="Bidirectional Slack integration with command support",
            version="1.3.0",
            rating=4.7,
            install_count=2567,
            icon_url="/static/icons/slack.svg",
            category="integrations",
            dependencies=[],
            min_version="1.0.0",
            max_version="2.0.0",
        ),
        PluginInfo(
            id="plugin-dark-theme",
            name="Dark Mode Theme",
            author="Design Team",
            description="Premium dark theme with OLED optimization",
            version="1.1.0",
            rating=4.5,
            install_count=5123,
            icon_url="/static/icons/theme-dark.svg",
            category="themes",
            dependencies=[],
            min_version="1.0.0",
            max_version="2.0.0",
        ),
        PluginInfo(
            id="plugin-analytics",
            name="Analytics Dashboard",
            author="Analytics Pro",
            description="Real-time usage analytics and performance metrics",
            version="1.0.0",
            rating=4.4,
            install_count=1234,
            icon_url="/static/icons/analytics.svg",
            category="tools",
            dependencies=[],
            min_version="1.2.0",
            max_version="2.0.0",
        ),
        PluginInfo(
            id="plugin-agent-tutor",
            name="AI Tutor Agent",
            author="Education AI",
            description="Personalized learning agent with adaptive difficulty",
            version="1.2.0",
            rating=4.8,
            install_count=1987,
            icon_url="/static/icons/agent-tutor.svg",
            category="agents",
            dependencies=[],
            min_version="1.0.0",
            max_version="2.0.0",
        ),
    ]

    def __init__(self):
        """Initialize plugin store."""
        self._installed: dict[str, InstalledPlugin] = {}

    def search(
        self,
        query: str | None = None,
        category: str = "all",
        sort_by: str = "rating",
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[PluginInfo], int]:
        """Search available plugins.

        Args:
            query: Search query (name/author/description)
            category: Filter by category
            sort_by: Sort field (rating, installs, name, newest)
            limit: Max results
            offset: Pagination offset

        Returns:
            Tuple of (plugins, total_count)
        """
        results = list(self.AVAILABLE_PLUGINS)

        # Filter by category
        if category and category != "all":
            results = [p for p in results if p.category == category]

        # Search query
        if query:
            q = query.lower()
            results = [p for p in results if q in p.name.lower() or q in p.author.lower() or q in p.description.lower()]

        # Sort
        if sort_by == "rating":
            results.sort(key=lambda p: (-p.rating, -p.install_count))
        elif sort_by == "installs":
            results.sort(key=lambda p: -p.install_count)
        elif sort_by == "name":
            results.sort(key=lambda p: p.name)
        elif sort_by == "newest":
            results.sort(key=lambda p: p.version, reverse=True)

        total = len(results)
        paginated = results[offset : offset + limit]
        return paginated, total

    def get_by_id(self, plugin_id: str) -> PluginInfo | None:
        """Get plugin by ID."""
        for p in self.AVAILABLE_PLUGINS:
            if p.id == plugin_id:
                return p
        return None

    def get_installed(self) -> dict[str, InstalledPlugin]:
        """Get all installed plugins."""
        return dict(self._installed)

    def is_installed(self, plugin_id: str) -> bool:
        """Check if plugin is installed."""
        return plugin_id in self._installed

    def install(self, plugin_id: str) -> InstalledPlugin:
        """Install a plugin."""
        if plugin_id in self._installed:
            raise PluginInstallException(f"Plugin {plugin_id} already installed")

        available = self.get_by_id(plugin_id)
        if not available:
            raise PluginNotFoundException(f"Plugin {plugin_id} not found in marketplace")

        installed = InstalledPlugin(
            id=plugin_id,
            name=available.name,
            version=available.version,
            enabled=True,
            installed_at=datetime.utcnow().isoformat(),
        )
        self._installed[plugin_id] = installed
        log.info(f"Installed plugin {plugin_id} v{available.version}")
        return installed

    def uninstall(self, plugin_id: str) -> None:
        """Uninstall a plugin."""
        if plugin_id not in self._installed:
            raise PluginInstallException(f"Plugin {plugin_id} not installed")
        del self._installed[plugin_id]
        log.info(f"Uninstalled plugin {plugin_id}")

    def toggle(self, plugin_id: str, enabled: bool) -> InstalledPlugin:
        """Enable or disable a plugin."""
        if plugin_id not in self._installed:
            raise PluginInstallException(f"Plugin {plugin_id} not installed")

        plugin = self._installed[plugin_id]
        plugin.enabled = enabled
        log.info(f"Plugin {plugin_id} {'enabled' if enabled else 'disabled'}")
        return plugin


# Global plugin store instance
_plugin_store: PluginStore | None = None


def get_plugin_store(app: web.Application) -> PluginStore:
    """Get or create plugin store from app context."""
    global _plugin_store
    if _plugin_store is None:
        _plugin_store = PluginStore()
    return _plugin_store


async def api_plugins_marketplace(request: web.Request) -> web.Response:
    """GET /api/plugins/marketplace - List available plugins."""
    try:
        store = get_plugin_store(request.app)

        # Parse query parameters
        query = request.query.get("q", "").strip()
        category = request.query.get("category", "all")
        sort_by = request.query.get("sort", "rating")
        limit = min(int(request.query.get("limit", "20")), 100)
        offset = int(request.query.get("offset", "0"))

        plugins, total = store.search(
            query=query or None,
            category=category,
            sort_by=sort_by,
            limit=limit,
            offset=offset,
        )

        return web.json_response(
            {
                "plugins": [asdict(p) for p in plugins],
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        )
    except Exception as e:
        log.exception("Error listing plugins")
        return web.json_response(
            {"error": str(e)},
            status=500,
        )


async def api_plugins_marketplace_detail(request: web.Request) -> web.Response:
    """GET /api/plugins/marketplace/{id} - Get plugin details."""
    try:
        plugin_id = request.match_info["id"]
        store = get_plugin_store(request.app)

        plugin = store.get_by_id(plugin_id)
        if not plugin:
            return web.json_response(
                {"error": f"Plugin {plugin_id} not found"},
                status=404,
            )

        installed = store.is_installed(plugin_id)
        result = asdict(plugin)
        result["installed"] = installed

        return web.json_response(result)
    except Exception as e:
        log.exception("Error getting plugin detail")
        return web.json_response(
            {"error": str(e)},
            status=500,
        )


async def api_plugins_install(request: web.Request) -> web.Response:
    """POST /api/plugins/install - Install a plugin."""
    try:
        data = await request.json()
        plugin_id = data.get("id", "").strip()

        if not plugin_id:
            return web.json_response(
                {"error": "Plugin ID required"},
                status=400,
            )

        store = get_plugin_store(request.app)

        try:
            installed = store.install(plugin_id)
            return web.json_response(
                {
                    "success": True,
                    "plugin": asdict(installed),
                }
            )
        except PluginNotFoundException as e:
            return web.json_response(
                {"error": str(e)},
                status=404,
            )
        except PluginInstallException as e:
            return web.json_response(
                {"error": str(e)},
                status=400,
            )
    except json.JSONDecodeError:
        return web.json_response(
            {"error": "Invalid JSON"},
            status=400,
        )
    except Exception as e:
        log.exception("Error installing plugin")
        return web.json_response(
            {"error": str(e)},
            status=500,
        )


async def api_plugins_uninstall(request: web.Request) -> web.Response:
    """POST /api/plugins/uninstall - Uninstall a plugin."""
    try:
        data = await request.json()
        plugin_id = data.get("id", "").strip()

        if not plugin_id:
            return web.json_response(
                {"error": "Plugin ID required"},
                status=400,
            )

        store = get_plugin_store(request.app)

        try:
            store.uninstall(plugin_id)
            return web.json_response({"success": True})
        except PluginInstallException as e:
            return web.json_response(
                {"error": str(e)},
                status=400,
            )
    except json.JSONDecodeError:
        return web.json_response(
            {"error": "Invalid JSON"},
            status=400,
        )
    except Exception as e:
        log.exception("Error uninstalling plugin")
        return web.json_response(
            {"error": str(e)},
            status=500,
        )


async def api_plugins_installed(request: web.Request) -> web.Response:
    """GET /api/plugins/installed - List installed plugins."""
    try:
        store = get_plugin_store(request.app)
        installed = store.get_installed()

        return web.json_response(
            {
                "plugins": [asdict(p) for p in installed.values()],
                "count": len(installed),
            }
        )
    except Exception as e:
        log.exception("Error listing installed plugins")
        return web.json_response(
            {"error": str(e)},
            status=500,
        )


async def api_plugins_toggle(request: web.Request) -> web.Response:
    """POST /api/plugins/toggle - Enable/disable a plugin."""
    try:
        data = await request.json()
        plugin_id = data.get("id", "").strip()
        enabled = data.get("enabled", True)

        if not plugin_id:
            return web.json_response(
                {"error": "Plugin ID required"},
                status=400,
            )

        store = get_plugin_store(request.app)

        try:
            plugin = store.toggle(plugin_id, enabled)
            return web.json_response(
                {
                    "success": True,
                    "plugin": asdict(plugin),
                }
            )
        except PluginInstallException as e:
            return web.json_response(
                {"error": str(e)},
                status=400,
            )
    except json.JSONDecodeError:
        return web.json_response(
            {"error": "Invalid JSON"},
            status=400,
        )
    except Exception as e:
        log.exception("Error toggling plugin")
        return web.json_response(
            {"error": str(e)},
            status=500,
        )


def register_marketplace_routes(app: web.Application) -> None:
    """Register marketplace routes in the application.

    Routes:
      GET /api/plugins/marketplace
      GET /api/plugins/marketplace/{id}
      POST /api/plugins/install
      POST /api/plugins/uninstall
      GET /api/plugins/installed
      POST /api/plugins/toggle
    """
    app.router.add_get("/api/plugins/marketplace", api_plugins_marketplace)
    app.router.add_get("/api/plugins/marketplace/{id}", api_plugins_marketplace_detail)
    app.router.add_post("/api/plugins/install", api_plugins_install)
    app.router.add_post("/api/plugins/uninstall", api_plugins_uninstall)
    app.router.add_get("/api/plugins/installed", api_plugins_installed)
    app.router.add_post("/api/plugins/toggle", api_plugins_toggle)

    log.info("Plugin marketplace routes registered")
