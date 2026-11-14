"""The model routes, as a row: the seven that list your models and test a connection, and the daily refresh behind them.

Off takes these routes away and stops the daily refresh of the model list. Nothing else here stops, but a lot of pages ask
these routes. The model button in the top bar of Chat, Build and Work reads Loading with no models in its menu, and a
message sent from Chat or Build is refused on the page with ``The selected model is not ready in this tab``, so off blocks
chatting from the page until the row is back. A page loaded while the row was on keeps its models until it reloads. Easy
Setup's Connect and Test ends in a failure, and the Companion page keeps reading loading. None of them asks again in a
loop. The words in ``default.toml`` say all of this to the person turning it off.

Chat itself, reached some other way, does not use these routes: it reads your models from the server's config and takes
their keys from the secret store, neither of which this row touches. ``/api/version`` is not one of these routes: the
server answers it itself. A refresh of the list that was already running when the row stopped is not cancelled and
finishes on its own, and a test of a connection that is running is waited for. A connection test of a local Ollama can
start Ollama, and nothing here stops that. The list is kept in a file, so what the last refresh found is there again when
the row comes back, and a new refresh starts then (unless the environment turns that off). ``/api/openai-codex/models``
reads the same list and falls back to Thomas's own list of ChatGPT models while this is off.

The first log line below is pinned word for word by ``tests/test_server_app_routes_init.py``, and every failure is
followed by a raise, so a row that cannot register reads failed rather than active with no routes.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class _Models:
    name = "models"
    inject = ("web",)
    imports = ("thomas.models.catalog_refresh", "thomas.server.routes.models_aiohttp")

    def apply(self, ctx: Any, config: Any) -> None:
        service = ctx["web"]
        if not callable(service.require_api_access):
            log.warning("Models route registration skipped: missing runtime dependencies")
            raise RuntimeError("models has no access guard to register with")
        try:
            from thomas.server.app_keys import APP_SECRETS
            from thomas.server.model_credentials import embed_credentials
            from thomas.server.routes.models_aiohttp import register_models_routes

            def model_cfg_for_profile(profile: str) -> Any:
                model_cfg = service.config.models.get(profile)
                if model_cfg is None:
                    raise KeyError(profile)
                return embed_credentials(model_cfg, profile, service.app.get(APP_SECRETS))

            register_models_routes(
                service.view(ctx),
                require_api_access=service.require_api_access,
                model_cfg_with_secrets=model_cfg_for_profile,
            )
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError) as exc:
            log.warning("Models routes unavailable: %s", exc)
            raise


plugin = _Models()
