"""Publish to GitHub, as a row: the two routes behind the Publish to GitHub section of Settings, and the preview they hold.

Off takes both routes away and removes the copy of the tree a preview made in a scratch folder. A release that was
already being sent carries on: it is a push from a worker thread, which a stop waits for but cannot end. Nothing here
runs on its own. The preview is built only when the section asks for it, and sending needs a Windows sign-in for that
exact preview each time.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class _PublicRelease:
    name = "public_release"
    inject = ("web",)
    imports = ("thomas.server.routes.public_release_routes",)

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.server.routes import public_release_routes as routes

        service = ctx["web"]
        # The folder this server's code runs from; a copy without the release tool answers in words instead.
        repo = Path(routes.__file__).resolve().parents[3]
        jobs = routes.ReleaseJobs(routes.CheckoutBackend(repo), ctx.task)
        routes.register_public_release_routes(
            service.view(ctx),
            jobs=jobs,
            require_api_access=service.require_api_access,
            require_loopback=service.require_loopback,
            read_json=service.read_json,
        )
        ctx.on_stopped(jobs.stop)


plugin = _PublicRelease()
