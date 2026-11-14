"""The search routes, as a row: ``/api/search`` and the twelve that hang off it.

Off takes these routes away and nothing else. One of them, ``/api/search/web``, fills the results page you reach from
either Search or type a URL box, so that page says it could not load. It asks the ``web.search`` tool, which is on the
server's own list, so chat goes on searching the web. The other twelve serve one store, ``thomas/core/search_history.py``,
which stays on disk: an index of conversations, with bookmarks and saved searches beside it. No page calls those twelve,
and the bookmarks bar in the window is a separate list, kept by the browser.

Two of the log lines below are pinned word for word by ``tests/test_server_app_routes_init.py``. Each is followed by a
raise, so a row that cannot register reads failed rather than active with no routes.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class _Search:
    name = "search"
    inject = ("web",)
    imports = ("thomas.server.routes.search",)

    def apply(self, ctx: Any, config: Any) -> None:
        service = ctx["web"]
        if not callable(service.require_api_access):
            log.warning("Search route registration skipped: missing runtime dependencies")
            raise RuntimeError("search has no access guard to register with")
        try:
            from thomas.server.routes.search import register_search_routes

            register_search_routes(service.view(ctx), require_api_access=service.require_api_access)
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError, ValueError) as exc:
            log.warning("Search routes unavailable: %s", exc)
            raise


plugin = _Search()
