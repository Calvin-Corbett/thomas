"""Pull request review, as a row: the eight ``/api/pr-review`` routes behind one section of the Agent Ops page.

Off takes the routes away and leaves the section on the page, which cannot tell and goes on reading LIVE. A review is
held in memory, in the one ``PrReviewStore`` the route file keeps for the process. Nothing here resets it, so reviews come
back with the routes, their numbers go on, and a page left open carries on where it was. Resetting it would start the
numbers again at pr1 and point a page left open at someone else's review. A restart loses them, on or off. The route
file writes two app keys, which the view takes back at a stop. Nothing else in Thomas reads a review.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

from typing import Any


class _PrReview:
    name = "pr_review"
    inject = ("web",)
    imports = ("thomas.server.routes.pr_review_routes", "thomas.tools.pr_review")

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.server.routes.pr_review_routes import register_pr_review_routes

        service = ctx["web"]
        register_pr_review_routes(service.view(ctx), service.config)


plugin = _PrReview()
