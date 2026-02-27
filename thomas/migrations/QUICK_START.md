# Thomas Migrations - Quick Start

## Installation

```bash
pip install alembic
```

## Integration (One-Time Setup)

Add to `thomas/server/app.py` in the `create_app()` function:

```python
def create_app(config: Optional[AppConfig] = None):
    from aiohttp import web

    if config is None:
        config = load_config()

    # ← ADD THIS BLOCK:
    try:
        from thomas.server.db_init import init_databases
        init_databases(config.memory.root_path)
    except ImportError:
        log.warning("Database migrations not available (alembic not installed)")

    # Rest of app creation...
    app = web.Application(client_max_size=25 * 1024 * 1024)
```

## Common Commands

```bash
# Show current database version
python -m thomas.migrations.migrate current

# Apply all pending migrations
python -m thomas.migrations.migrate upgrade

# Revert one migration
python -m thomas.migrations.migrate downgrade

# Show all migrations
python -m thomas.migrations.migrate history
```

## Creating a New Migration

1. Create file: `thomas/migrations/versions/NNN_description.py`

```python
"""
NNN_description

Brief description.

Revision ID: NNN
Revises: NNN-1
Create Date: 2025-02-26
"""

from alembic import op
import sqlalchemy as sa

revision = "NNN"
down_revision = "NNN-1"

def upgrade() -> None:
    """Apply the migration."""
    op.add_column("table_name", sa.Column("new_col", sa.String(255)))

def downgrade() -> None:
    """Revert the migration."""
    op.drop_column("table_name", "new_col")
```

2. Test:
```bash
python -m thomas.migrations.migrate upgrade
python -m thomas.migrations.migrate current
```

3. Commit and deploy

## Database Location

Auto-detected in this order:
1. `THOMAS_DB_PATH` env var
2. `THOMAS_SQLITE_PATH` env var
3. `~/.thomas/thomas.db` (default)

Override with:
```bash
export THOMAS_DB_PATH=/custom/path/to/db.sqlite3
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Alembic not installed" | `pip install alembic` |
| "Cannot determine version" | `python -m thomas.migrations.migrate upgrade` |
| Database locked | Close other connections |
| Need to backup before migration | `cp ~/.thomas/thomas.db ~/.thomas/thomas.db.backup` |

## Key Files

| File | Purpose |
|------|---------|
| `migrations/migrate.py` | Main migration API |
| `migrations/env.py` | Database connection config |
| `migrations/versions/` | Migration files |
| `server/db_init.py` | Server integration hook |
| `INTEGRATION_GUIDE.md` | Full documentation |

## Python API

```python
# Server startup (best place)
from thomas.server.db_init import init_databases
init_databases()

# Manual migrations
from thomas.migrations.migrate import run_migrations, current_version
run_migrations(direction="upgrade")
version = current_version()

# Health check
from thomas.server.db_init import check_database_health
health = check_database_health()
```

## Initial Schema (001)

Includes all existing Thomas tables:
- preferences, thread_preferences
- runs, events
- search_history tables
- autonomy tables (jobs, approvals, audit, etc.)
- asset_studio tables

No data loss for existing databases (automatic stamping).

---

For full documentation, see `INTEGRATION_GUIDE.md`
