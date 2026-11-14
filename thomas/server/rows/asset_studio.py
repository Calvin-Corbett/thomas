"""Asset Studio, as a row: the 39 ``/api/asset-studio/v1`` routes and the jobs they start.

Off takes the routes away, drops anything reading a job's events, and ends the jobs. The registrar writes a job runner
and a ComfyUI service to the app and adds a cleanup, all through the view. So once running requests have ended the
cleanup ends each job's process, marks the job cancelled and closes the store, then the view takes the keys back and on
builds a new pair, not one whose store has closed. A request waiting on a job holds the stop, and the job runs on until
then. Jobs, templates and webhook settings stay in ``thomas.asset_studio.db`` in the data folder, and on reads them back.

The cleanup goes no further than the shell that ran a boot command. On Windows ComfyUI is a child of that shell, so the
shell ends, ComfyUI goes on running, and the new service knows nothing of it. Stop on the page has the same limit with
this on, so the row's words say close it yourself.

Chat's two tools in ``thomas/marketplace/asset_studio/tools.py`` load with or without this, and neither reaches the store.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

from typing import Any


class _AssetStudio:
    name = "asset_studio"
    inject = ("web",)
    imports = ("thomas.server.routes.asset_studio_aiohttp",)

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.server.routes.asset_studio_aiohttp import register_asset_studio_routes

        service = ctx["web"]
        register_asset_studio_routes(
            service.view(ctx, streams=("/api/asset-studio/v1/jobs/{job_id}/events/stream",)),
            require_api_access=service.require_api_access,
            read_json=service.read_json,
        )


plugin = _AssetStudio()
