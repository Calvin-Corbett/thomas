"""Core aiohttp route registration for the web UI + JSON API."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from aiohttp import web

_ROUTES: tuple[tuple[str, str, str], ...] = (
    ("get", "/api/models", "api_models"),
    ("get", "/api/models/capabilities", "api_models_capabilities"),
    ("get", "/api/models/{profile}/ids", "api_profile_models"),
    ("get", "/api/models/{profile}/handshake", "api_profile_handshake"),
    ("get", "/api/models/{profile}/validate", "api_profile_validate"),
    ("get", "/api/version", "api_version"),
    ("get", "/api/setup/bootstrap", "api_setup_bootstrap"),
    ("post", "/api/setup/repair", "api_setup_repair"),
    ("get", "/api/engines", "api_engines"),
    ("get", "/api/tools", "api_tools"),
    ("get", "/api/chats", "api_chats"),
    ("put", "/api/chats/{chat_id}", "api_chat_put"),
    ("delete", "/api/chats/{chat_id}", "api_chat_delete"),
    ("get", "/api/secrets", "api_secrets"),
    ("post", "/api/secrets/{profile}", "api_secret_set"),
    ("delete", "/api/secrets/{profile}", "api_secret_clear"),
    ("post", "/api/local/pull", "api_local_pull"),
    ("post", "/api/session/new", "api_session_new"),
    ("post", "/api/session/fork", "api_session_fork"),
    ("post", "/api/session/import", "api_session_import"),
    ("post", "/api/chat", "api_chat"),
)


def register_core_routes(
    app: web.Application,
    *,
    web_dir: Path,
    handlers: Mapping[str, Any],
) -> None:
    app.router.add_get("/", handlers["index"])
    if "settings" in handlers:
        app.router.add_get("/settings", handlers["settings"])
    if "companion" in handlers:
        app.router.add_get("/companion", handlers["companion"])
    app.router.add_static("/static/", web_dir, show_index=False)
    for method, path, handler_name in _ROUTES:
        handler = handlers[handler_name]
        getattr(app.router, f"add_{method}")(path, handler)
