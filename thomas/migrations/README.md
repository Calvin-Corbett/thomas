# Thomas Database Migrations

Welcome to the Thomas database migration system! This directory contains Alembic-based database schema versioning and management tools for all Thomas SQLite databases.

## Quick Navigation

### For Quick Start
- **[QUICK_START.md](QUICK_START.md)** - Common commands and basic usage (5 min read)

### For Integration
- **[SERVER_INTEGRATION_PATCH.md](SERVER_INTEGRATION_PATCH.md)** - Exactly what code to add to `thomas/server/app.py` (10 min read)

### For Complete Details
- **[INTEGRATION_GUIDE.md](INTEGRATION_GUIDE.md)** - Comprehensive documentation (30 min read)

### For Setup Verification
- **[verify_setup.py](verify_setup.py)** - Run to verify all files and dependencies are correct

## What This System Does

The Thomas migration system provides:

1. **Automatic Schema Versioning** - Track database schema changes with migration files
2. **Upgrade/Downgrade Support** - Apply or revert migrations safely
3. **Existing Database Handling** - Seamlessly upgrade databases without data loss
4. **Zero Dependencies** - Works without Alembic installed (degraded mode)
5. **Production Ready** - Comprehensive error handling and logging

## Installation

```bash
pip install alembic
```

That's it! The system works without Alembic, but it's highly recommended.

## Getting Started (30 seconds)

1. **Check current version**:
   ```bash
   python -m thomas.migrations.migrate current
   ```

2. **Apply pending migrations**:
   ```bash
   python -m thomas.migrations.migrate upgrade
   ```

3. **See migration history**:
   ```bash
   python -m thomas.migrations.migrate history
   ```

## Integration (5 minutes)

Add this to `thomas/server/app.py` in the `create_app()` function:

```python
try:
    from thomas.server.db_init import init_databases
    init_databases(config.memory.root_path)
except ImportError:
    log.warning("Database migrations not available (alembic not installed)")
```

See [SERVER_INTEGRATION_PATCH.md](SERVER_INTEGRATION_PATCH.md) for exact details.

## Directory Structure

```
thomas/migrations/
├── alembic.ini                          # Alembic configuration
├── env.py                               # Database connection setup
├── migrate.py                           # Main migration helper module (380 lines)
├── __init__.py                          # Package initialization
│
├── versions/                            # Migration files
│   ├── __init__.py
│   ├── 001_initial_schema.py           # Baseline schema (all existing tables)
│   └── 002_add_migration_tracking.py   # Example: adds migration tracking
│
├── QUICK_START.md                       # Quick reference
├── INTEGRATION_GUIDE.md                 # Full documentation
├── SERVER_INTEGRATION_PATCH.md          # Code to add to app.py
├── README.md                            # This file
└── verify_setup.py                      # Setup verification script

thomas/server/
└── db_init.py                           # Server startup integration hook
```

## Key Files

| File | Purpose | Size |
|------|---------|------|
| `migrate.py` | Main migration API and CLI | 380 lines |
| `env.py` | Database discovery and connection | 145 lines |
| `001_initial_schema.py` | Baseline schema with all tables | 385 lines |
| `server/db_init.py` | Server startup integration | 95 lines |

All files are under 400 lines for maximum readability.

## Common Tasks

### Check if migrations are needed
```bash
python -m thomas.migrations.migrate current
```

### Apply all pending migrations
```bash
python -m thomas.migrations.migrate upgrade
```

### Revert one migration
```bash
python -m thomas.migrations.migrate downgrade
```

### See all migrations and their status
```bash
python -m thomas.migrations.migrate history
```

### Use in Python code
```python
from thomas.migrations.migrate import init_database, current_version

# Initialize at startup
init_database()

# Check version
version = current_version()
print(f"Database schema version: {version}")
```

## Database Discovery

The system automatically finds the Thomas database in this order:

1. `THOMAS_DB_PATH` environment variable (preferred)
2. `THOMAS_SQLITE_PATH` environment variable (legacy)
3. From `thomas.preferences.store.get_db_path()`
4. Default: `~/.thomas/thomas.db`

Override manually:
```bash
export THOMAS_DB_PATH=/custom/path/to/db.sqlite3
python -m thomas.migrations.migrate current
```

## Creating New Migrations

To add a new migration:

1. Create file `versions/NNN_description.py`:

```python
"""
NNN_description

Brief description of what this migration does.

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
    # Add your schema changes here
    op.add_column("table_name", sa.Column("new_col", sa.String(255)))

def downgrade() -> None:
    """Revert the migration."""
    op.drop_column("table_name", "new_col")
```

2. Test it:
```bash
python -m thomas.migrations.migrate upgrade
python -m thomas.migrations.migrate current
```

3. Commit to version control and deploy

See [INTEGRATION_GUIDE.md](INTEGRATION_GUIDE.md) for detailed examples.

## Handling Existing Databases

When upgrading an existing Thomas installation:

1. The migration system detects existing tables
2. Automatically stamps the database with version 001
3. Subsequent migrations apply normally
4. **No data is lost** - existing tables are preserved

This makes migrations safe for production deployments.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Alembic not installed" | `pip install alembic` |
| "Cannot determine version" | `python -m thomas.migrations.migrate upgrade` |
| "Database locked" | Close other connections to the database |
| "Column already exists" | Expected for existing DB - stamping handles this |

See [INTEGRATION_GUIDE.md](INTEGRATION_GUIDE.md) for more troubleshooting.

## Initial Schema (001_initial_schema.py)

The baseline migration creates all current Thomas tables:

**Preferences System**: preferences, preferences_meta, thread_preferences

**Run Tracking**: runs, events

**Search & History**: search_history_meta, turn_map, turn_index, query_history, bookmarks, saved_searches

**Autonomy**: schema_version, jobs, approvals, audit, autonomy_messages, briefings

**Asset Studio**: asset_studio_jobs, asset_studio_job_events, asset_studio_templates, asset_studio_webhook_configs, asset_studio_template_webhook_configs

## Production Checklist

Before deploying to production:

- [ ] Install Alembic: `pip install alembic`
- [ ] Test on staging environment
- [ ] Backup database: `cp ~/.thomas/thomas.db ~/.thomas/thomas.db.backup`
- [ ] Add integration code to `thomas/server/app.py`
- [ ] Verify migrations run successfully
- [ ] Monitor logs for any issues
- [ ] Confirm database health: `python -m thomas.migrations.migrate current`

## Support & Help

- **Quick questions**: See [QUICK_START.md](QUICK_START.md)
- **Integration help**: See [SERVER_INTEGRATION_PATCH.md](SERVER_INTEGRATION_PATCH.md)
- **Detailed info**: See [INTEGRATION_GUIDE.md](INTEGRATION_GUIDE.md)
- **Verify setup**: Run `python verify_setup.py`

## Features

✓ Automatic database versioning
✓ Safe upgrade/downgrade
✓ Existing database support (no data loss)
✓ Programmatic API
✓ Command-line interface
✓ Health checking
✓ Automatic database discovery
✓ Graceful degradation without Alembic
✓ Comprehensive error handling
✓ Production-ready

## Key Implementation Details

- **Pure SQLite** - No ORM required, uses raw SQL via alembic.op
- **Auto-discovery** - Finds database location automatically
- **Idempotent** - Safe to call multiple times
- **Backward compatible** - Works with existing databases
- **Well documented** - Comprehensive guides and examples

## Version History

| Version | Changes |
|---------|---------|
| 001 | Initial schema with all existing tables |
| 002 | Add migration tracking table (_migrations_meta) |

## See Also

- Project setup summary: `/sessions/intelligent-magical-ptolemy/mnt/Thomas/MIGRATIONS_SETUP.md`
- Server integration details: [SERVER_INTEGRATION_PATCH.md](SERVER_INTEGRATION_PATCH.md)

---

**Status**: Production Ready
**Created**: 2025-02-26
**Maintained By**: Thomas Development Team

For questions or issues, see the [INTEGRATION_GUIDE.md](INTEGRATION_GUIDE.md) troubleshooting section.
