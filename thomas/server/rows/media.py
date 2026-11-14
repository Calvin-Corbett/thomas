"""Creating images, video and music, as a row: the four ``/api/media`` routes and the jobs they start.

Off takes the routes away, cancels each job's two tasks and records the job as cancelled. It does not wait for a job,
because a stop cancels the worker's task itself, and it cannot end the worker thread under that task: Python cannot stop
a thread. So a model already rendering, or a request already with the provider, goes on to its end with nothing reading
the result. It leaves its file in the job's workspace, and because the record says cancelled nothing offers that file. A
worker on a local model holds ``_LOCAL_LOCK`` until it ends, and that lock is at the top of a module that stays loaded, so
a new job after on waits its turn rather than loading a second model onto the GPU.

Your choice of model or key, in ``media_lanes.json`` and the secret store, stays. Finished files are served by
``/deliverable``, so chats and Library go on showing them. A job's progress is held in the registrar, so on starts with
none of it, and a page that asks about an older job is answered from the task record.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class _Media:
    name = "media"
    inject = ("web",)
    imports = ("thomas.server.routes.media_generation_routes",)

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.server.routes.media_generation_routes import setup_media_generation_routes

        service = ctx["web"]
        setup_media_generation_routes(
            service.view(ctx),
            data_root=Path(service.config.memory.root_path),
            require_api_access=service.require_api_access,
            start_task=ctx.task,
        )


plugin = _Media()
