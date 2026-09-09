"""Thomas playing a game it built, streamed move by move.

Split out of ``evolve_agent_routes`` because it is the only endpoint in the
Code surface that drives a browser and a vision model instead of a build
subprocess. It shares nothing with the launcher but the conversation resolver:
no run registry, no transcript, no approvals. Keeping it here means the game
loop (headless browser, per-move decision, final report) can grow without
adding a line to the file that starts and stops runs.

The heavy imports stay INSIDE the handler on purpose. A playtest pulls in an
LLM client and the CDP driver; paying for that at import time would tax every
server start for a route most sessions never call, and it keeps this module
free of any import-order relationship with the rest of ``thomas.server``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.forge.anvil import forge_code_projects

log = logging.getLogger(__name__)


def build_evolve_agent_playtest_handlers(
    app: web.Application,
    *,
    require_api_access: Callable[[web.Request], None],
    project_for_conversation: Callable[[str], Path],
) -> dict[str, Any]:
    """Build the playtest handler against the routes module's conversation resolver."""

    async def playtest_stream(request: web.Request) -> web.StreamResponse:
        """Stream Thomas actually playtesting a built game (SSE).

        A server-side headless browser plays the game while a vision model
        decides each move; the events (what Thomas sees, plays, notes, and
        concludes) stream to the viewer. Honest failure: if the browser or the
        model is unavailable, that arrives as an error event, not silence.
        """
        require_api_access(request)
        from thomas.core.config import load_config
        from thomas.core.llm import LLMError
        from thomas.core.llm_client import LLMClient
        from thomas.server.app_keys import APP_SECRETS
        from thomas.server.game_playtest import CdpError, PlaytestEvent, playtest_game
        from thomas.server.openai_codex_oauth import ensure_openai_codex_access_token

        # Every fault a playtest can actually hit, named. Anything outside this
        # set is a bug and must surface, not be swallowed into an event.
        _PLAYTEST_FAULTS = (CdpError, LLMError, OSError, RuntimeError, ValueError, TypeError, KeyError)

        cid = str(request.query.get("conversation_id") or "").strip()
        rel = str(request.query.get("file") or "index.html").strip()
        if not cid or ".." in rel.replace("\\", "/").split("/"):
            raise web.HTTPBadRequest(text="conversation_id and a safe file are required")
        try:
            project_root = project_for_conversation(cid)
        except forge_code_projects.ForgeCodeProjectError as exc:
            raise web.HTTPConflict(text=str(exc)) from exc
        game_path = (project_root / rel).resolve()
        if not (game_path == project_root or project_root in game_path.parents) or not game_path.is_file():
            raise web.HTTPNotFound(text="game file not found")

        response = web.StreamResponse(
            headers={"Content-Type": "text/event-stream", "Cache-Control": "no-store", "X-Accel-Buffering": "no"}
        )
        await response.prepare(request)

        queue: asyncio.Queue[PlaytestEvent | None] = asyncio.Queue()

        async def sink(event: PlaytestEvent) -> None:
            await queue.put(event)

        async def drive() -> None:
            llm = None
            try:
                secret_store = app.get(APP_SECRETS)
                token = (
                    await ensure_openai_codex_access_token("openai_codex", secret_store=secret_store)
                    if secret_store
                    else ""
                )
                if not token:
                    await queue.put(
                        PlaytestEvent(
                            "error",
                            "Thomas needs the ChatGPT login connected to playtest — reconnect it in settings.",
                        )
                    )
                    return
                config = load_config(project_root / "thomas.toml")
                model_cfg = config.get_model("openai_codex")
                model_cfg.api_key = token
                # Per-move "what's my next move" needs speed, not deep
                # reasoning — low effort roughly halves the decision latency
                # (measured 5.6s -> ~2.7s). The final report is a separate call
                # that keeps the model's default effort.
                model_cfg.reasoning_effort = "low"
                llm = LLMClient(model_cfg, fallback_configs=[], failover_enabled=False)
                title = game_path.stem.replace("_", " ").replace("-", " ").title()
                await playtest_game(game_url=game_path.as_uri(), llm=llm, game_title=title, on_event=sink, max_moves=10)
            except _PLAYTEST_FAULTS as exc:
                # Named faults only: the browser refusing to drive (CdpError),
                # the model failing (LLMError), the login/config being wrong,
                # or the OS denying the browser. CancelledError is deliberately
                # NOT caught — a cancelled stream must stay cancelled.
                log.info("Playtest stopped: %s", exc)
                await queue.put(PlaytestEvent("error", f"The playtest stopped: {exc}"))
            finally:
                if llm is not None:
                    with contextlib.suppress(OSError, RuntimeError):
                        await llm.close()
                await queue.put(None)

        task = asyncio.create_task(drive())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    await response.write(b'data: {"kind": "end"}\n\n')
                    break
                payload = json.dumps({"kind": event.kind, "text": event.text, "data": event.data}, ensure_ascii=False)
                await response.write(f"data: {payload}\n\n".encode())
        finally:
            task.cancel()
            with contextlib.suppress(Exception):
                await task
        return response

    return {"playtest_stream": playtest_stream}
