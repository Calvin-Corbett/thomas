"""The cage window, as a row: read-only routes that show what the caged Thomas runs, what each run is doing, and what a
self-fix has changed.

Off takes the seven ``/api/inspect/...`` routes away and nothing else: the cage, its runs and its self-fix copies carry
on exactly as they did, you just cannot look at them from outside the cage through this. The cage's account still
refuses yours, so with this off the only way to see inside is to ask Thomas himself.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class _CageInspector:
    name = "cage_inspector"
    inject = ("web",)
    imports = (
        "thomas.core.cage_inspector",
        "thomas.core.cage_processes",
        "thomas.server.routes.cage_inspector_routes",
    )

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.core import green_place, project_root
        from thomas.server.routes.cage_inspector_routes import register_cage_inspector_routes

        service = ctx["web"]
        if not callable(service.require_api_access):  # the registrar reads no guard as a route open to everyone
            raise RuntimeError("cage_inspector has no access guard to register with")
        register_cage_inspector_routes(
            service.view(ctx),
            require_api_access=service.require_api_access,
            agent_dir=lambda: Path(project_root.code_checkout()) / ".thomas" / "evolve" / "agent",
            green_root=green_place.green_root,
        )


plugin = _CageInspector()
