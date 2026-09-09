# Server Integration Patch

This document shows exactly where and how to integrate migrations into `thomas/server/app.py`.

## Location in create_app()

Find the `create_app()` function in `thomas/server/app.py` around line 432:

```python
def create_app(config: Optional[AppConfig] = None):
    from aiohttp import web

    if config is None:
        config = load_config()

    # INSERT CODE HERE (see below)

    app = web.Application(client_max_size=25 * 1024 * 1024)  # 25 MB
```

## Code to Insert

Add this right after the `config = load_config()` line and before `app = web.Application(...)`:

```python
    # ── Initialize databases and run migrations ──
    try:
        from thomas.server.db_init import init_databases
        init_databases(config.memory.root_path)
        log.info("Database migrations completed")
    except ImportError:
        log.warning(
            "Database migrations not available; install with: pip install alembic"
        )
    except Exception as e:
        log.error(f"Database initialization failed: {e}")
        log.warning("Continuing without database migrations")
```

## Before and After

### Before (Current Code)

```python
def create_app(config: Optional[AppConfig] = None):
    from aiohttp import web

    if config is None:
        config = load_config()

    # AppKey constants imported from thomas.server.app_keys

    app = web.Application(client_max_size=25 * 1024 * 1024)  # 25 MB
    app[APP_CONFIG] = config
    # ... rest of implementation
```

### After (With Migrations)

```python
def create_app(config: Optional[AppConfig] = None):
    from aiohttp import web

    if config is None:
        config = load_config()

    # ── Initialize databases and run migrations ──
    try:
        from thomas.server.db_init import init_databases
        init_databases(config.memory.root_path)
        log.info("Database migrations completed")
    except ImportError:
        log.warning(
            "Database migrations not available; install with: pip install alembic"
        )
    except Exception as e:
        log.error(f"Database initialization failed: {e}")
        log.warning("Continuing without database migrations")

    # AppKey constants imported from thomas.server.app_keys

    app = web.Application(client_max_size=25 * 1024 * 1024)  # 25 MB
    app[APP_CONFIG] = config
    # ... rest of implementation
```

## What This Does

1. **Imports the initialization function** from `thomas.server.db_init`
2. **Calls `init_databases()`** with the memory root path
3. **Logs success** when migrations complete
4. **Handles ImportError** gracefully if Alembic is not installed
5. **Handles exceptions** and logs warnings but doesn't crash
6. **Allows server to start** even if migrations fail (degraded mode)

## Expected Log Output

When the server starts with the migration hook installed:

```
2025-02-26 10:30:15 - thomas.migrations.migrate - INFO - Using database at /home/user/.thomas/thomas.db
2025-02-26 10:30:15 - thomas.server.db_init - INFO - Database initialization completed
2025-02-26 10:30:15 - thomas.server.app - INFO - Database schema version: 002
```

If Alembic is not installed:

```
2025-02-26 10:30:15 - thomas.server.app - WARNING - Database migrations not available; install with: pip install alembic
```

If migrations fail (rare):

```
2025-02-26 10:30:15 - thomas.server.app - ERROR - Database initialization failed: <error details>
2025-02-26 10:30:15 - thomas.server.app - WARNING - Continuing without database migrations
```

## Optional: Health Check Endpoint

To add a database health check endpoint, add this to a routes file (e.g., `thomas/server/routes/health.py`):

```python
async def get_database_health(request: web.Request) -> web.Response:
    """Return database health status."""
    from thomas.server.db_init import check_database_health

    health = check_database_health()
    status = "healthy" if all(health.values()) else "degraded"

    return web.json_response({
        "status": status,
        "databases": health,
    })

# Then register in app setup:
# app.router.add_get("/api/health/db", get_database_health)
```

Example response:

```json
{
  "status": "healthy",
  "databases": {
    "preferences": true,
    "runs": true,
    "migrations": true
  }
}
```

## Line-by-Line Explanation

```python
# Line 1: Try to import and run migrations
try:
    # Import the initialization helper
    from thomas.server.db_init import init_databases

    # Call it with the configured memory root path
    # This ensures all databases are created and up-to-date
    init_databases(config.memory.root_path)

    # Log success
    log.info("Database migrations completed")

# Line 2: Handle missing Alembic
except ImportError:
    log.warning(
        "Database migrations not available; install with: pip install alembic"
    )

# Line 3: Handle any other errors
except Exception as e:
    log.error(f"Database initialization failed: {e}")
    log.warning("Continuing without database migrations")
```

## Testing the Integration

After adding the migration hook to `create_app()`:

1. **Restart the server**:
   ```bash
   python -m thomas.server
   ```

2. **Check the logs** - should show successful database initialization

3. **Verify the database was created**:
   ```bash
   ls -lh ~/.thomas/thomas.db
   ```

4. **Check schema version**:
   ```bash
   python -m thomas.migrations.migrate current
   ```

5. **View migration history**:
   ```bash
   python -m thomas.migrations.migrate history
   ```

## Rollback (If Needed)

If you need to remove this change:

1. Remove the try/except block added above
2. Server will continue to work as before
3. Existing databases are not affected
4. Migrations can be run manually later if needed

## Production Deployment

For production deployments:

1. **Install Alembic**: `pip install alembic`
2. **Add the integration** as shown above
3. **Test in staging** first
4. **Back up database** before deploying to production
5. **Deploy and monitor logs**

The migration system is safe and backward compatible. It won't break existing functionality.

---

See `QUICK_START.md` for quick reference
See `INTEGRATION_GUIDE.md` for complete documentation
