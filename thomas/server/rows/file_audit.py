"""The file change record routes, as a row: ``/api/audit/files`` and ``/api/audit/runs/{run_id}/files``.

Off takes these two routes away and nothing else. The server goes on starting the record in ``.thomas/file_audit.db``
inside the memory folder, and the agent loop goes on noting each file a run writes there, whether the routes are
present or not.

Today the routes answer with nothing: they read ``thomas.observability.file_audit``, which the bridge in
``thomas/observability/__init__.py`` loads as a second copy of the module the server and the loop use, and nothing
points that copy at the database. The row keeps that as it was.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

from typing import Any


class _FileAudit:
    name = "file_audit"
    inject = ("web",)
    imports = ("thomas.server.routes.audit",)

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.server.routes.audit import register_audit_routes

        service = ctx["web"]
        register_audit_routes(service.view(ctx), require_api_access=service.require_api_access)


plugin = _FileAudit()
