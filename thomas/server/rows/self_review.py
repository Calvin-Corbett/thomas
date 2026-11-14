"""Thomas's review of its own recent work, as a row: ``GET /api/self-review``.

Off takes the route away, cancels a review being written in the background, and forgets the reports held in memory, so
the next time the row is on the first ask starts a review again. A copy of the last finished report stays in
``runtime/logs/self_review.md``, and nothing here touches the failure list or your chats, which the review only reads.

Asking for it starts a call to the model, so the server's own access check runs before the handler: this machine only,
or, when Thomas is open to other computers, a caller that sends the access key. In the shell the route had no check.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

from typing import Any

from aiohttp import web


class _SelfReview:
    name = "self_review"
    inject = ("web",)
    imports = ("thomas.server.routes.self_review",)

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.server.routes.self_review import (
            APP_SELF_REVIEW_CACHE,
            end_self_review_work,
            handle_self_review,
            new_self_review_cache,
        )

        service = ctx["web"]
        view = service.view(ctx)
        # Made here, before the server is handed to its runner, as it was in create_app. The view takes the key back on stop.
        cache = new_self_review_cache()
        view[APP_SELF_REVIEW_CACHE] = cache

        async def self_review_for_a_caller_let_in(request: web.Request) -> web.StreamResponse:
            # Read when asked, not when the row loads: the check is made once the server's middleware is up, and a
            # server with no check refuses rather than answers.
            guard = service.require_api_access
            if not callable(guard):
                raise web.HTTPInternalServerError(text="server access guard is not configured")
            guard(request)
            return await handle_self_review(request)

        view.router.add_get("/api/self-review", self_review_for_a_caller_let_in)

        async def end_the_reviews_being_written() -> None:
            await end_self_review_work(cache)

        ctx.on_stopped(end_the_reviews_being_written)


plugin = _SelfReview()
