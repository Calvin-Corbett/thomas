"""The task-ledger routes, as a row: ``/api/task-ledger/current``, ``/api/task-ledger/history`` and their underscore twins.

Off takes these four routes away and nothing else. The ledger is the record Thomas keeps of the task each chat is on, and
it goes on being written while the routes are away, because the replies write it and the routes only read it. The older
full page reads these routes to fill its Current Task panel.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

from typing import Any


class _TaskLedger:
    name = "task_ledger"
    inject = ("web",)
    imports = ("thomas.server.task_ledger_routes",)

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.server.task_ledger_routes import register_task_ledger_routes

        service = ctx["web"]
        register_task_ledger_routes(service.view(ctx), require_api_access=service.require_api_access)


plugin = _TaskLedger()
