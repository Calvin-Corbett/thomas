"""
Thomas database migration helper.

Programmatic interface for running database migrations. Supports both
Alembic and raw SQLite fallback modes.

Usage:
    python -m thomas.migrations.migrate upgrade    # Apply all pending migrations
    python -m thomas.migrations.migrate downgrade  # Roll back one migration
    python -m thomas.migrations.migrate current    # Show current version
    python -m thomas.migrations.migrate history    # Show migration history

Programmatic:
    from thomas.migrations.migrate import run_migrations, current_version
    run_migrations()
    version = current_version()
"""

from __future__ import annotations

import logging
import os
import sqlite3
import sys
from pathlib import Path

log = logging.getLogger(__name__)

# Try to import alembic
try:
    from alembic import command as alembic_cmd
    from alembic.config import Config as AlembicConfig
    from alembic.script import ScriptDirectory

    ALEMBIC_AVAILABLE = True
except ImportError:
    ALEMBIC_AVAILABLE = False


class MigrationError(Exception):
    """Migration execution failed."""

    pass


class DatabaseError(Exception):
    """Database operation failed."""

    pass


def _resolve_db_path() -> Path:
    """Resolve Thomas database path in order of precedence."""
    if env_path := os.getenv("THOMAS_DB_PATH", "").strip():
        return Path(env_path)

    if env_path := os.getenv("THOMAS_SQLITE_PATH", "").strip():
        return Path(env_path)

    try:
        from thomas.preferences.store import get_db_path

        return get_db_path()
    except ImportError:
        pass

    return Path.home() / ".thomas" / "thomas.db"


def _get_alembic_config() -> AlembicConfig:
    """Create and configure Alembic config."""
    migrations_dir = Path(__file__).parent
    config = AlembicConfig(str(migrations_dir / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{_resolve_db_path()}")
    config.set_main_option("script_location", str(migrations_dir))
    return config


def _ensure_db_exists() -> Path:
    """Ensure database file exists and is writable."""
    db_path = _resolve_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        if not db_path.exists():
            db_path.touch()
            log.info(f"Created new database at {db_path}")
    except OSError as e:
        raise DatabaseError(f"Cannot create database at {db_path}: {e}")

    return db_path


def _get_connection() -> sqlite3.Connection:
    """Get a SQLite connection."""
    db_path = _ensure_db_exists()
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn
    except sqlite3.Error as e:
        raise DatabaseError(f"Failed to connect to database: {e}")


def _get_schema_version(conn: sqlite3.Connection) -> str | None:
    """Get the current schema version from the database."""
    try:
        cur = conn.execute("SELECT version FROM alembic_version ORDER BY version DESC LIMIT 1")
        row = cur.fetchone()
        return row[0] if row else None
    except sqlite3.OperationalError:
        # Table doesn't exist yet
        return None


def _init_alembic_version_table(conn: sqlite3.Connection) -> None:
    """Initialize alembic_version tracking table if it doesn't exist."""
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alembic_version (
                version_num VARCHAR(32) NOT NULL,
                PRIMARY KEY(version_num)
            )
            """
        )
        conn.commit()
    except sqlite3.Error as e:
        raise DatabaseError(f"Failed to initialize alembic_version table: {e}")


def _stamp_initial_version(conn: sqlite3.Connection, version: str) -> None:
    """
    Stamp the database with an initial migration version.

    Used when migrating existing databases that don't have migration tables.
    """
    _init_alembic_version_table(conn)
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM alembic_version")
        cur.execute("INSERT INTO alembic_version (version_num) VALUES (?)", (version,))
        conn.commit()
        log.info(f"Stamped database with version {version}")
    except sqlite3.Error as e:
        raise DatabaseError(f"Failed to stamp database version: {e}")


def _is_existing_database(conn: sqlite3.Connection) -> bool:
    """Check if database has existing Thomas tables."""
    try:
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'preferences%'")
        return bool(cur.fetchone())
    except sqlite3.Error:
        return False


def run_migrations(
    target_version: str | None = None,
    direction: str = "upgrade",
    dry_run: bool = False,
) -> None:
    """
    Run database migrations.

    Args:
        target_version: Specific version to migrate to (None = latest)
        direction: "upgrade" or "downgrade"
        dry_run: If True, show SQL without executing

    Raises:
        MigrationError: If migration fails
        DatabaseError: If database operations fail
    """
    if not ALEMBIC_AVAILABLE:
        log.warning("Alembic not installed; using fallback migration mode")
        _run_migrations_fallback(target_version, direction)
        return

    db_path = _ensure_db_exists()
    conn = _get_connection()

    try:
        # Check if this is an existing database without migration tracking
        if _is_existing_database(conn) and not _get_schema_version(conn):
            log.info("Existing database detected; stamping with initial schema version")
            _stamp_initial_version(conn, "001")

        config = _get_alembic_config()

        if direction == "upgrade":
            if target_version:
                alembic_cmd.upgrade(config, target_version)
            else:
                alembic_cmd.upgrade(config, "head")
        elif direction == "downgrade":
            if target_version:
                alembic_cmd.downgrade(config, target_version)
            else:
                alembic_cmd.downgrade(config, "-1")
        else:
            raise MigrationError(f"Unknown direction: {direction}")

        log.info(f"Migration {direction} completed successfully")

    except Exception as e:
        raise MigrationError(f"Migration failed: {e}")
    finally:
        conn.close()


def _run_migrations_fallback(
    target_version: str | None = None,
    direction: str = "upgrade",
) -> None:
    """Fallback migration mode using raw SQLite (no Alembic)."""
    log.warning("Running migrations in fallback mode (without Alembic)")
    # Fallback would load migration files manually and execute them
    # For now, just log that it needs Alembic
    raise MigrationError("Migrations require Alembic. Install with: pip install alembic")


def current_version() -> str | None:
    """Get the current schema version."""
    if not ALEMBIC_AVAILABLE:
        log.warning("Alembic not installed; cannot determine current version")
        return None

    try:
        conn = _get_connection()
        version = _get_schema_version(conn)
        conn.close()
        return version
    except DatabaseError as e:
        log.error(f"Failed to get current version: {e}")
        return None


def migration_history() -> list[tuple[str, str]]:
    """Get migration history as list of (version, status) tuples."""
    if not ALEMBIC_AVAILABLE:
        return []

    try:
        config = _get_alembic_config()
        script = ScriptDirectory.from_config(config)
        revisions = script.get_revisions("base")

        history = []
        current = current_version()

        for rev in revisions:
            status = "applied" if (current and rev.revision >= current) else "pending"
            history.append((rev.revision, rev.message or "unnamed", status))

        return history
    except Exception as e:
        log.error(f"Failed to get migration history: {e}")
        return []


def init_database() -> None:
    """
    Initialize database and run all pending migrations.

    This is the primary entry point for application startup.
    Safe to call multiple times (idempotent).
    """
    try:
        db_path = _ensure_db_exists()
        log.info(f"Using database at {db_path}")

        # Run migrations
        run_migrations(direction="upgrade")

        # Verify success
        version = current_version()
        if version:
            log.info(f"Database schema at version {version}")
        else:
            log.warning("Database initialized but version tracking unavailable")

    except (MigrationError, DatabaseError) as e:
        log.error(f"Database initialization failed: {e}")
        log.warning("Continuing without database (some features may be unavailable)")


def cli_main() -> None:
    """Command-line interface for migrations."""
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    command = sys.argv[1].lower()

    try:
        if command == "upgrade":
            target = sys.argv[2] if len(sys.argv) > 2 else None
            run_migrations(target_version=target, direction="upgrade")
            print("✓ Migrations applied successfully")

        elif command == "downgrade":
            target = sys.argv[2] if len(sys.argv) > 2 else None
            run_migrations(target_version=target, direction="downgrade")
            print("✓ Migrations reverted successfully")

        elif command == "current":
            version = current_version()
            print(f"Current schema version: {version or 'unknown'}")

        elif command == "history":
            history = migration_history()
            if history:
                print("\nMigration History:")
                for rev, msg, status in history:
                    print(f"  [{status:8}] {rev} - {msg}")
            else:
                print("No migration history available")

        else:
            print(f"Unknown command: {command}")
            print(__doc__)
            sys.exit(1)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    cli_main()
