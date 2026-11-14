"""Workspaces, linked projects and source notes, as a row: 35 routes that three pages and a few buttons use.

``/api/workspaces*`` is the list of workspaces, members and invites kept in ``.thomas/workspaces.sqlite3``.
``/api/local/*`` is the linked-projects registry in ``.thomas/linked_projects.json``, which My Stuff, the project pickers
in Chat and Code, and the Library read. ``/api/source-annotations*`` is the notes left on lines of source, kept in
``.thomas/source_annotations.json``. Off takes the routes away and nothing else: all three files stay, and Chat and the
workspace specialist go on reading and changing the linked-projects file themselves.

Three things run on while this is on, and the row ends each:

- The workspaces database opens in a worker thread, in a startup step, so turning this on in a running server does not
  stop it answering while the file opens. The routes join once it is open. Off closes it.
- A scan that rebuilds the list of projects can be running in the background. Off cancels it. Its worker thread cannot be
  ended and finishes by itself, and its result is dropped.
- The source notes runtime is a module-level value, so a stop clears it and the next start reads the file again.

``thomas/server/rows/__init__.py`` says how a row is written. Two of the log lines below are pinned word for word by
``tests/test_server_app_routes_init.py``, each followed by a raise, so a row that cannot register reads failed rather
than active with no routes.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class _Workspace:
    name = "workspace"
    inject = ("web",)
    imports = (
        "thomas.server.routes.local_projects_aiohttp",
        "thomas.server.routes.source_annotation_routes",
        "thomas.server.workspace.router",
    )

    def apply(self, ctx: Any, config: Any) -> None:
        service = ctx["web"]
        if not all(callable(dep) for dep in (service.require_api_access, service.require_loopback, service.read_json)):
            log.warning("Local project route registration skipped: missing runtime dependencies")
            raise RuntimeError("local projects have no guards to register with")
        view = service.view(ctx)
        try:
            from thomas.server.routes.local_projects_aiohttp import register_local_project_routes
            from thomas.server.routes.local_projects_registry import stop_catalogue_rebuild

            register_local_project_routes(
                view,
                require_api_access=service.require_api_access,
                require_loopback=service.require_loopback,
                read_json=service.read_json,
            )

            async def stop_the_scan() -> None:
                await stop_catalogue_rebuild(view)

            ctx.on_stopped(stop_the_scan)
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError, ValueError) as exc:
            log.warning("Local project routes unavailable: %s", exc)
            raise

        try:
            from thomas.server.workspace.router import setup as setup_workspace_router

            setup_workspace_router(view, service.config, require_api_access=service.require_api_access)
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError, ValueError) as exc:
            log.warning("Workspace routes unavailable: %s", exc)
            raise

        try:
            from thomas.server.routes.source_annotation_routes import (
                register_source_annotation_routes,
                reset_source_annotation_runtime,
            )

            register_source_annotation_routes(view, service.config, require_api_access=service.require_api_access)

            async def forget_the_notes_runtime() -> None:
                reset_source_annotation_runtime()

            ctx.on_stopped(forget_the_notes_runtime)
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError, ValueError) as exc:
            log.warning("Source note routes unavailable: %s", exc)
            raise


plugin = _Workspace()
