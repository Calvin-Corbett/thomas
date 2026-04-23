"""Thomas HTTP server and web UI package.

Provides a lightweight aiohttp-based server for serving the Thomas UI
and exposing REST APIs for chat, model management, and configuration.

Main exports:
- init_databases: Initialize and migrate all Thomas databases
- db_init: Module with database initialization functions

Note: create_app is available via thomas.server.app module but not
re-exported here to avoid circular dependencies and heavy imports.
Use: from thomas.server.app import create_app
"""

from thomas.server import db_init

__all__ = [
    "db_init",
]
