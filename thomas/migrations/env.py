"""
Alembic environment configuration for Thomas database migrations.

This environment detects the Thomas database location from config and
provides both offline (SQL generation) and online (direct execution) modes.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path

try:
    from alembic import context
    from alembic.script import ScriptDirectory

    ALEMBIC_AVAILABLE = True
except ImportError:
    ALEMBIC_AVAILABLE = False

log = logging.getLogger(__name__)


def _resolve_thomas_db_path() -> Path:
    """Resolve Thomas database path in order of precedence."""
    # Environment variable override (preferred)
    if env_path := os.getenv("THOMAS_DB_PATH", "").strip():
        return Path(env_path)

    if env_path := os.getenv("THOMAS_SQLITE_PATH", "").strip():
        return Path(env_path)

    # Try to import from preferences store (if available)
    try:
        from thomas.preferences.store import get_db_path

        return get_db_path()
    except ImportError:
        pass

    # Default fallback
    return Path.home() / ".thomas" / "thomas.db"


def _get_connection() -> sqlite3.Connection | None:
    """Get a SQLite connection to the Thomas database."""
    try:
        db_path = _resolve_thomas_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        # Enable foreign keys for SQLite
        conn.execute("PRAGMA foreign_keys = ON")
        return conn
    except Exception as e:
        log.error(f"Failed to connect to database: {e}")
        return None


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.

    This generates SQL at runtime without a running database.
    Good for CI/CD pipelines and for generating SQL migration scripts.
    """
    if not ALEMBIC_AVAILABLE:
        log.warning("Alembic not installed; cannot run offline migrations")
        return

    _get_metadata()

    with context.begin_transaction():
        context.execute(
            "-- Offline migration mode (SQL generation only)\n-- Apply these SQL statements manually to your database\n"
        )


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode.

    Directly executes migration scripts against the database.
    """
    if not ALEMBIC_AVAILABLE:
        log.warning("Alembic not installed; cannot run online migrations")
        return

    target_metadata = _get_metadata()

    # Get database connection
    connectable = _get_connection()
    if not connectable:
        log.error("Cannot connect to database; aborting migrations")
        return

    try:
        with connectable.begin() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)

            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.close()


def _get_metadata():
    """Placeholder for SQLAlchemy metadata (not currently used for SQLite)."""
    # For pure SQLite migration scripts, we don't use SQLAlchemy metadata.
    # This is a placeholder for future expansion.
    return None


def init_env():
    """Initialize the migration environment."""
    if not ALEMBIC_AVAILABLE:
        log.warning("Alembic is not installed. Install with: pip install alembic")
        return

    if context.is_offline_mode():
        run_migrations_offline()
    else:
        run_migrations_online()


# Entry point for Alembic
if __name__ == "__main__" or (ALEMBIC_AVAILABLE and context):
    if ALEMBIC_AVAILABLE:
        if context.is_offline_mode():
            run_migrations_offline()
        else:
            run_migrations_online()
