"""
Thomas Database Migrations

Provides database migration management for Thomas SQLite databases.
Supports both Alembic-based migrations and raw SQLite fallback.

Usage:
    # Programmatic API
    from thomas.migrations.migrate import run_migrations, current_version
    run_migrations()  # Apply all pending migrations
    print(current_version())  # Show current schema version

    # Command line
    python -m thomas.migrations.migrate upgrade
    python -m thomas.migrations.migrate downgrade
    python -m thomas.migrations.migrate history
"""

__version__ = "1.0.0"
