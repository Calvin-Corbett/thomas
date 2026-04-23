"""Thomas-owned routes for Discord bridge lifecycle, config, and history."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from aiohttp import web

from thomas.channels.discord_bridge_runtime import DiscordBridgeRuntime
from thomas.core.config import AppConfig

RequireAccessFn = Callable[[web.Request], None]
ReadJsonFn = Callable[[web.Request], Any]


def register_discord_channels_routes(
    app: web.Application,
    *,
    config: AppConfig,
    require_api_access: RequireAccessFn,
    read_json: ReadJsonFn,
) -> None:
    runtime = DiscordBridgeRuntime(config)

    async def api_discord_status(request: web.Request) -> web.Response:
        require_api_access(request)
        payload = await asyncio.to_thread(runtime.status)
        return web.json_response({"ok": True, "discord": payload})

    async def api_discord_config(request: web.Request) -> web.Response:
        require_api_access(request)
        payload = await read_json(request)
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="payload must be a JSON object")
        env = await asyncio.to_thread(runtime.update_env, payload)
        status = await asyncio.to_thread(runtime.status)
        return web.json_response({"ok": True, "env_keys": sorted(env.keys()), "discord": status})

    async def api_discord_runtime(request: web.Request) -> web.Response:
        require_api_access(request)
        payload = await read_json(request)
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="payload must be a JSON object")
        restart_if_running = bool(payload.pop("restart_if_running", False))
        try:
            result = await asyncio.to_thread(
                runtime.update_runtime_settings,
                payload,
                restart_if_running=restart_if_running,
            )
        except RuntimeError as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc
        status = await asyncio.to_thread(runtime.status)
        return web.json_response({"ok": True, **result, "discord": status})

    async def api_discord_enabled(request: web.Request) -> web.Response:
        require_api_access(request)
        payload = await read_json(request)
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="payload must be a JSON object")
        if "enabled" not in payload:
            raise web.HTTPBadRequest(text="enabled is required")
        state = await asyncio.to_thread(runtime.set_enabled, bool(payload.get("enabled")))
        return web.json_response({"ok": True, "state": state, "discord": runtime.status()})

    async def api_discord_start(request: web.Request) -> web.Response:
        require_api_access(request)
        try:
            payload = await asyncio.to_thread(runtime.start)
        except RuntimeError as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc
        return web.json_response({"ok": True, "discord": payload})

    async def api_discord_stop(request: web.Request) -> web.Response:
        require_api_access(request)
        try:
            payload = await asyncio.to_thread(runtime.stop)
        except RuntimeError as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc
        return web.json_response({"ok": True, "discord": payload})

    async def api_discord_restart(request: web.Request) -> web.Response:
        require_api_access(request)
        try:
            payload = await asyncio.to_thread(runtime.restart)
        except RuntimeError as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc
        return web.json_response({"ok": True, "discord": payload})

    async def api_discord_voice_probe(request: web.Request) -> web.Response:
        require_api_access(request)
        payload = await read_json(request)
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="payload must be a JSON object")
        try:
            result = await asyncio.to_thread(
                runtime.run_voice_probe,
                wake=str(payload.get("wake") or ""),
                ask=str(payload.get("ask") or ""),
                say=str(payload.get("say") or ""),
                speaker_name=str(payload.get("speaker_name") or "Voice Probe"),
                speaker_id=str(payload.get("speaker_id") or ""),
                channel=str(payload.get("channel") or ""),
                keep_audio=bool(payload.get("keep_audio")),
                probe_backend=str(payload.get("probe_backend") or "windows"),
            )
        except RuntimeError as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc
        return web.json_response({"ok": True, **result, "discord": runtime.status()})

    async def api_discord_history(request: web.Request) -> web.Response:
        require_api_access(request)
        query = str(request.query.get("q") or "").strip()
        session_id = str(request.query.get("session_id") or "").strip()
        try:
            limit = max(1, min(int(str(request.query.get("limit") or "20")), 100))
        except (TypeError, ValueError) as exc:
            raise web.HTTPBadRequest(text="invalid limit") from exc
        sessions = await asyncio.to_thread(runtime.list_sessions, limit=limit, query=query)
        hits = await asyncio.to_thread(runtime.search_history, query=query, limit=limit, session_id=session_id)
        return web.json_response(
            {
                "ok": True,
                "query": query,
                "session_id": session_id,
                "sessions": sessions,
                "hits": hits,
            }
        )

    async def api_discord_session_context(request: web.Request) -> web.Response:
        require_api_access(request)
        session_id = str(request.match_info.get("session_id") or "").strip()
        if not session_id:
            raise web.HTTPBadRequest(text="missing session_id")
        try:
            limit = max(1, min(int(str(request.query.get("limit") or "12")), 100))
        except (TypeError, ValueError) as exc:
            raise web.HTTPBadRequest(text="invalid limit") from exc
        payload = await asyncio.to_thread(runtime.get_session_context, session_id, limit=limit)
        return web.json_response({"ok": True, **payload})

    app.router.add_get("/api/channels/discord", api_discord_status)
    app.router.add_post("/api/channels/discord/config", api_discord_config)
    app.router.add_post("/api/channels/discord/runtime", api_discord_runtime)
    app.router.add_post("/api/channels/discord/runtime-settings", api_discord_runtime)
    app.router.add_post("/api/channels/discord/enabled", api_discord_enabled)
    app.router.add_post("/api/channels/discord/start", api_discord_start)
    app.router.add_post("/api/channels/discord/stop", api_discord_stop)
    app.router.add_post("/api/channels/discord/restart", api_discord_restart)
    app.router.add_post("/api/channels/discord/voice-probe", api_discord_voice_probe)
    app.router.add_get("/api/channels/discord/history", api_discord_history)
    app.router.add_get("/api/channels/discord/history/{session_id}", api_discord_session_context)
