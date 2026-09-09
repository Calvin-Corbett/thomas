# Thomas Database Migrations - Integration Guide

## Overview

This guide explains how to integrate Alembic database migrations into the Thomas server and CLI.

## Setup Status

The migration system is now set up with:

- **Alembic configuration** (`alembic.ini`)
- **Environment configuration** (`env.py`) - handles SQLite database discovery
- **Migration helper** (`migrate.py`) - programmatic API and CLI interface
- **Server initialization hook** (`server/db_init.py`) - startup integration point
- **Initial schema** (`versions/001_initial_schema.py`) - baseline schema with all current tables
- **Example migration** (`versions/002_add_migration_tracking.py`) - demonstrates migration capabilities

## Integration Steps

### Step 1: Install Alembic (if not already installed)

```bash
pip install alembic
```

### Step 2: Add Migration Hook to Server Startup

In `thomas/server/app.py`, add this near the top of the `create_app()` function (after imports but before creating the app instance):

```python
def create_app(config: Optional[AppConfig] = None):
    from aiohttp import web

    if config is None:
        config = load_config()

    # Initialize databases and run migrations
    try:
        from thomas.server.db_init import init_databases
        init_databases(config.memory.root_path)
    except ImportError:
        log.warning("Database migrations not available (alembic not installed)")

    # Create app instance
    app = web.Application(client_max_size=25 * 1024 * 1024)
    # ... rest of app creation
```

### Step 3: (Optional) Add Migration Health Check Endpoint

In `thomas/server/routes/health.py` or similar, add:

```python
async def get_database_health(request: web.Request) -> web.Response:
    """Return database health status."""
    from thomas.server.db_init import check_database_health

    health = check_database_health()
    return web.json_response({
        "status": "healthy" if all(health.values()) else "degraded",
        "databases": health,
    })
```

## Usage

### Command Line

```bash
# Apply all pending migrations
python -m thomas.migrations.migrate upgrade

# Revert one migration
python -m thomas.migrations.migrate downgrade

# Show current schema version
python -m thomas.migrations.migrate current

# Show migration history
python -m thomas.migrations.migrate history
```

### Programmatic (in Python code)

```python
from thomas.migrations.migrate import run_migrations, current_version, init_database

# Initialize database on startup
init_database()

# Get current version
version = current_version()
print(f"Schema version: {version}")

# Apply specific version
run_migrations(target_version="002", direction="upgrade")
```

### Server startup

When the Thomas server starts, migrations will automatically run:

```
2025-02-26 10:30:15 - thomas.migrations.migrate - INFO - Using database at /home/user/.thomas/thomas.db
2025-02-26 10:30:15 - thomas.server.db_init - INFO - Database initialization completed
2025-02-26 10:30:15 - thomas.server.app - INFO - Database schema version: 002
```

## Database Discovery

The migration system automatically discovers the Thomas database location in this order:

1. `THOMAS_DB_PATH` environment variable (preferred)
2. `THOMAS_SQLITE_PATH` environment variable (legacy)
3. Imported from `thomas.preferences.store.get_db_path()` if available
4. Default: `~/.thomas/thomas.db`

## Handling Existing Databases

When upgrading an existing Thomas installation:

1. The migration system detects if the database already has Thomas tables
2. If migration tracking is not present, it "stamps" the database with version 001
3. This means existing databases skip the initial schema creation
4. Subsequent migrations (002+) are applied normally

**No existing data is lost** - the stamping process only records that the current schema matches version 001.

## Creating New Migrations

To create a new migration:

### 1. Create the migration file

```python
# thomas/migrations/versions/003_your_migration_name.py

"""
003_your_migration_name

Brief description of what this migration does.

Revision ID: 003
Revises: 002
Create Date: 2025-02-26
"""

from alembic import op
import sqlalchemy as sa


revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""
    op.add_column("some_table", sa.Column("new_column", sa.String(255)))


def downgrade() -> None:
    """Revert the migration."""
    op.drop_column("some_table", "new_column")
```

### 2. Test the migration

```bash
# Test upgrade
python -m thomas.migrations.migrate upgrade 003

# Verify it worked
python -m thomas.migrations.migrate current

# Test downgrade
python -m thomas.migrations.migrate downgrade 002

# Verify it reverted
python -m thomas.migrations.migrate current
```

### 3. Commit and deploy

Once tested, commit the migration file to version control. Deployments will automatically run it.

## Troubleshooting

### "Alembic not installed"

Install Alembic:
```bash
pip install alembic
```

### "Cannot determine current version"

This usually means:
1. Database doesn't exist yet (will be created on first upgrade)
2. Migration tracking table is corrupted (rare)

Solution:
```python
from thomas.migrations.migrate import init_database
init_database()  # This will fix it
```

### "Migration failed"

Check the error message and logs. Common issues:
- Database is locked (close other connections)
- Foreign key constraint violations (check data integrity)
- Column already exists (if manually creating schema)

### Reverting a deployed migration

```bash
# Revert to previous version
python -m thomas.migrations.migrate downgrade 001

# Or downgrade one step
python -m thomas.migrations.migrate downgrade
```

## Database Backup Before Major Migrations

Before applying migrations to production, always backup:

```bash
cp ~/.thomas/thomas.db ~/.thomas/thomas.db.backup.$(date +%Y%m%d_%H%M%S)
```

Then test the migration on a copy:

```bash
cp ~/.thomas/thomas.db.backup /tmp/thomas_test.db
THOMAS_DB_PATH=/tmp/thomas_test.db python -m thomas.migrations.migrate upgrade
```

## SQLite-Specific Notes

Thomas uses SQLite as its default database. The migration system:

- Automatically enables foreign keys (`PRAGMA foreign_keys = ON`)
- Uses raw SQLite operations via `alembic.op`
- Does NOT require SQLAlchemy ORM models
- Supports offline SQL generation mode (useful for auditing)

## Performance Considerations

Migrations are typically fast for SQLite (microseconds to seconds), but:

- Large data migrations may take longer
- Indexes are created/dropped as needed
- No downtime required for most migrations

Monitor migration time:

```bash
time python -m thomas.migrations.migrate upgrade
```

## Next Steps

1. **Install Alembic** if not already installed
2. **Integrate the migration hook** into `thomas/server/app.py`
3. **Test with an existing database** (recommended to use a backup first)
4. **Create migrations** as schema needs evolve
5. **Monitor database health** using the provided health check endpoint

## Support

For issues or questions:

1. Check the troubleshooting section above
2. Review migration files in `thomas/migrations/versions/`
3. Check logs for detailed error messages
4. Ensure Alembic is correctly installed

---

Generated: 2025-02-26
