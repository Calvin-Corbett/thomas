"""
Database initialization and migration hook for Thomas server startup.

Call this during app initialization to ensure all databases are up-to-date
and properly migrated.

Usage:
    from thomas.server.db_init import init_databases
    init_databases(config.memory.root_path)
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)


def init_databases(root_path: Path | None = None) -> None:
    """
    Initialize and migrate all Thomas databases.

    This is the main entry point for database setup during server startup.
    It runs all pending migrations and initializes database schemas.

    Args:
        root_path: Root directory for Thomas data. If None, uses THOMAS_DB_PATH env var
                  or defaults to ~/.thomas/

    Safe to call multiple times (idempotent) - migrations will only run if needed.
    """
    try:
        from thomas.migrations.migrate import init_database

        init_database()
        log.info("Database initialization completed")

    except ImportError as e:
        log.warning(
            f"Cannot initialize migrations (missing dependency): {e}. Install alembic with: pip install alembic"
        )
    except Exception as e:
        # Log error but don't crash - allow server to start in degraded mode
        log.error(f"Database initialization failed (some features may be unavailable): {e}")


def check_database_health() -> dict[str, bool]:
    """
    Check health of Thomas databases.

    Returns:
        Dictionary with health status of each database component.
    """
    health = {
        "preferences": False,
        "runs": False,
        "migrations": False,
    }

    try:
        # Check migrations
        from thomas.migrations.migrate import current_version

        version = current_version()
        health["migrations"] = version is not None
        if version:
            log.info(f"Database schema version: {version}")

    except Exception as e:
        log.warning(f"Migration health check failed: {e}")

    # Check if preferences database exists
    try:
        from thomas.preferences.store import get_db_path

        db_path = get_db_path()
        health["preferences"] = db_path.exists()
    except Exception as e:
        log.warning(f"Preferences database health check failed: {e}")

    # Check if runs database exists
    try:
        from thomas.observability.run_db import resolve_runs_db_path

        db_path = resolve_runs_db_path()
        health["runs"] = db_path.exists()
    except Exception as e:
        log.warning(f"Runs database health check failed: {e}")

    return health


__all__ = [
    "init_databases",
    "check_database_health",
]
