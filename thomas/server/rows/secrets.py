"""The secrets routes, as a row: ``/api/secrets`` and the three that hang off it.

Off takes these routes away and nothing else. The key store in ``thomas/server/secrets.py`` is opened at startup and
stays open, so the keys in it stay, and whatever reads them goes on reading them. What stops is saving a key from a page,
and any other program seeing, changing or removing keys here. The key boxes in Settings save to your preferences, and
ChatGPT sign-in and the media key box have routes of their own, so none of those pass through this row.

``tests/test_server_app_routes_init.py`` pins both log lines below, so they stay word for word, then raise so that a row
that cannot start reads failed.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class _Secrets:
    name = "secrets"
    inject = ("web",)
    imports = ("thomas.server.routes.secrets_aiohttp",)

    def apply(self, ctx: Any, config: Any) -> None:
        service = ctx["web"]
        if not callable(service.require_api_access) or not callable(service.read_json):
            log.warning("Secrets route registration skipped: missing runtime dependencies")
            raise RuntimeError("secrets has no access guard or body reader to register with")
        try:
            from thomas.server.routes.secrets_aiohttp import register_secrets_routes

            register_secrets_routes(
                service.view(ctx),
                require_api_access=service.require_api_access,
                read_json=service.read_json,
            )
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError, ValueError) as exc:
            log.warning("Secrets routes unavailable: %s", exc)
            raise


plugin = _Secrets()
