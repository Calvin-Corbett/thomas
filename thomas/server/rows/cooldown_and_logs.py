"""The rate limit line in Chat and the Export Logs button in Settings, as a row: the routes those two ask.

Off takes ``GET /api/chat/cooldowns`` and ``/api/logs/export`` away and nothing else. Both only read. The first reads what
the LLM client keeps about the models it is resting, so which model answers does not change, and the turn still sends the
page its own countdown. The second packs the logs folder, so Thomas goes on writing its logs.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


class _CooldownAndLogs:
    name = "cooldown_and_logs"
    inject = ("web",)
    imports = ("thomas.server.routes.cooldown_routes", "thomas.server.routes.logs_export_routes")

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.server.routes.cooldown_routes import setup_cooldown_routes
        from thomas.server.routes.logs_export_routes import setup_logs_export_routes

        service = ctx["web"]
        view = service.view(ctx)
        log_file = str(os.environ.get("THOMAS_LOG_FILE") or "").strip()
        logs_dir = Path(log_file).parent if log_file else Path(service.config.memory.root_path) / "logs"
        setup_cooldown_routes(view, require_api_access=service.require_api_access)
        setup_logs_export_routes(view, logs_dir=logs_dir, require_api_access=service.require_api_access)


plugin = _CooldownAndLogs()
