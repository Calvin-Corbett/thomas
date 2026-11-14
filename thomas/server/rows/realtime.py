"""The realtime page, as a row: ``/realtime``, its files, ``/api/realtime/ws`` and ``/api/realtime/upload``.

Nothing in Thomas uses this. No page links to it, so its address is the only way in, and it is here so that it can be
turned off. As it ships, ``runtime/.thomas/realtime.toml`` does not exist, so the feature's own setting is off: the socket
says it is disabled and closes, and an upload is refused.
The page's ``ws_client.js`` then tries again about twice a second until Connect is pressed a second time, because each try
opens before it is told, and an open resets its wait. With that setting changed the socket stays up and every message
comes back as an error, because nothing hands it the direct chat path and it asks ``/api/chat`` in a shape that route
answers with 400.

Off takes these routes away, drops anything on the socket, and takes back the settings and the guard this writes on the
app. A session holds everything it knows, so it ends with its socket, and a socket's two tasks end with its handler. On
reads the settings afresh. Files already uploaded stay where they were saved, and nothing reads them. The voice status
answer in ``thomas/server/routes/chat_v2_voice.py`` goes on naming the socket, and no page reads that.

The page's files sit in ``web/static/realtime``, beside the package, and ``routes._find_repo_root`` walks up from the
package to find them. A release bundle carries them. A pip copy inside the checkout, in the ``.venv`` that ``install.cmd``
and ``install.sh`` make, walks up into the checkout and finds them. The Docker image, or a pip copy anywhere else, finds
nothing, so this registers no folder of files and ``/realtime`` answers 404 from its own handler with the row on.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

from typing import Any


class _Realtime:
    name = "realtime"
    inject = ("web",)
    imports = ("thomas.marketplace.realtime.routes",)

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.marketplace.realtime.routes import setup_realtime_routes

        service = ctx["web"]
        setup_realtime_routes(
            service.view(ctx, streams=("/api/realtime/ws",)),
            require_api_access=service.require_api_access,
        )


plugin = _Realtime()
