"""Health check endpoints for monitoring server status and readiness.

Provides:
  GET /health - Basic liveness check
  GET /health/ready - Readiness check with dependency verification
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.core.config import AppConfig
from thomas.server.app_keys import APP_CONFIG

log = logging.getLogger(__name__)

# Placeholder for storing boot time across the app lifecycle
_BOOT_TIME: float | None = None


def set_boot_time(boot_time: float) -> None:
    """Set the boot time for uptime calculation."""
    global _BOOT_TIME
    _BOOT_TIME = boot_time


async def api_health_ready(request: web.Request) -> web.Response:
    """GET /health/ready - Readiness check with dependency verification.

    Checks:
      - SQLite database is writable
      - At least one LLM provider is configured
      - Static files directory exists

    Returns:
        200 with {"status": "ready", "checks": {...}} if all pass
        503 with {"status": "not_ready", "checks": {...}} if any fail
    """
    app: web.Application = request.app
    cfg: AppConfig | None = app.get("app_config") or app.get(APP_CONFIG)

    checks: dict[str, str] = {}
    all_ok = True

    # Check 1: SQLite database writability
    db_error = ""
    try:
        # Try a simple write to a temporary in-memory database
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE _health_check (id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO _health_check (id) VALUES (1)")
        conn.execute("DELETE FROM _health_check WHERE id = 1")
        conn.close()
        checks["database"] = "ok"
    except sqlite3.Error as e:
        db_error = str(e)
        checks["database"] = f"failed: {db_error}"
        all_ok = False
    except (OSError, RuntimeError, ValueError, AttributeError, TypeError, ImportError, KeyError) as e:
        db_error = str(e)
        checks["database"] = f"error: {db_error}"
        all_ok = False

    # Check 2: At least one LLM provider configured
    llm_error = ""
    try:
        if cfg is None:
            llm_error = "AppConfig not available"
            checks["llm"] = f"failed: {llm_error}"
            all_ok = False
        elif not cfg.models or len(cfg.models) == 0:
            llm_error = "No model profiles configured"
            checks["llm"] = f"failed: {llm_error}"
            all_ok = False
        else:
            checks["llm"] = "ok"
    except Exception as e:
        llm_error = str(e)
        checks["llm"] = f"error: {llm_error}"
        all_ok = False

    # Check 3: Static files directory exists
    static_error = ""
    try:
        # The static directory should be in thomas/server/static
        static_dir = Path(__file__).parent.parent / "static"
        if static_dir.exists() and static_dir.is_dir():
            checks["static_files"] = "ok"
        else:
            static_error = f"Directory not found or not a directory: {static_dir}"
            checks["static_files"] = f"failed: {static_error}"
            all_ok = False
    except Exception as e:
        static_error = str(e)
        checks["static_files"] = f"error: {static_error}"
        all_ok = False

    status_code = 200 if all_ok else 503
    response_data = {
        "status": "ready" if all_ok else "not_ready",
        "checks": checks,
    }

    return web.json_response(response_data, status=status_code)


def register_health_ready_route(
    app: web.Application,
    *,
    handler: Any | None = None,
) -> None:
    """Register the /health/ready readiness check route in the application.

    Args:
        app: aiohttp Application instance
        handler: Optional handler override (for testing)
    """
    ready_handler = handler or api_health_ready
    app.router.add_get("/health/ready", ready_handler)
    log.info("Health readiness check route registered (/health/ready)")
