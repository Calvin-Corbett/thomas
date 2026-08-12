"""aiohttp routes for native ChatGPT/Codex OAuth."""

from __future__ import annotations

import asyncio
import logging
import time
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass

from aiohttp import web

from thomas.core.codex_provider import OPENAI_CODEX_BASE_URL, OPENAI_CODEX_PROVIDER
from thomas.core.config import AppConfig
from thomas.server.app_keys import APP_CONFIG, APP_SECRETS
from thomas.server.openai_codex_oauth import (
    OPENAI_CODEX_REDIRECT_URI,
    OAuthStart,
    OpenAICodexOAuthError,
    clear_openai_codex_token,
    exchange_code_for_tokens,
    has_openai_codex_token,
    import_local_codex_token,
    parse_oauth_callback,
    public_token_status,
    read_openai_codex_token,
    start_oauth_flow,
    write_openai_codex_token,
)
from thomas.server.routes.openai_codex_aiohttp_helpers import (
    configured_codex_models as _configured_codex_models,
)
from thomas.server.routes.openai_codex_aiohttp_helpers import (
    profile_from_request as _profile_from_request,
)
from thomas.server.routes.openai_codex_aiohttp_helpers import (
    read_json_object as _read_json_object,
)

log = logging.getLogger(__name__)


@dataclass
class _PendingLogin:
    flow: OAuthStart
    callback_bound: bool
    event: asyncio.Event
    code: str = ""
    error: str = ""


class _OAuthCallbackServer:
    def __init__(self) -> None:
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._pending: dict[str, _PendingLogin] = {}
        self._lock = asyncio.Lock()

    async def start_flow(self, profile: str) -> _PendingLogin:
        async with self._lock:
            await self._start_server_locked()
            flow = start_oauth_flow(profile=profile, redirect_uri=OPENAI_CODEX_REDIRECT_URI)
            pending = _PendingLogin(
                flow=flow,
                callback_bound=self._site is not None,
                event=asyncio.Event(),
            )
            self._pending[flow.state] = pending
            return pending

    async def complete_from_callback(self, code: str, state: str) -> _PendingLogin | None:
        pending = self._pending.get(str(state or "").strip())
        if pending is None:
            return None
        pending.code = str(code or "").strip()
        pending.event.set()
        return pending

    def get_pending(self, state: str) -> _PendingLogin | None:
        return self._pending.get(str(state or "").strip())

    def finish(self, state: str) -> None:
        self._pending.pop(str(state or "").strip(), None)

    async def cleanup(self) -> None:
        async with self._lock:
            if self._runner is not None:
                await self._runner.cleanup()
            self._runner = None
            self._site = None
            self._pending.clear()

    async def _start_server_locked(self) -> None:
        if self._site is not None:
            return
        app = web.Application()
        app.router.add_get("/auth/callback", self._handle_callback)
        runner = web.AppRunner(app)
        try:
            await runner.setup()
            site = web.TCPSite(runner, "localhost", 1455)
            await site.start()
        # Binding the fixed loopback callback port: OSError covers "address in
        # use" and permission refusals, RuntimeError covers a runner/loop that is
        # already set up or shutting down. Sign-in then falls back to paste-the-URL.
        except (OSError, RuntimeError) as e:
            log.warning("Native ChatGPT OAuth callback server unavailable: %s", e)
            try:
                await runner.cleanup()
            except (OSError, RuntimeError):  # tearing down a runner that never came up
                log.debug("OAuth callback runner cleanup failed", exc_info=True)
            self._runner = None
            self._site = None
            return
        self._runner = runner
        self._site = site

    async def _handle_callback(self, request: web.Request) -> web.Response:
        state = str(request.query.get("state") or "").strip()
        code = str(request.query.get("code") or "").strip()
        error = str(request.query.get("error") or "").strip()
        pending = self._pending.get(state)
        if pending is None:
            return web.Response(
                text="<html><body><h1>Thomas sign-in</h1><p>This OAuth state is no longer pending.</p></body></html>",
                content_type="text/html",
                status=400,
            )
        if error:
            pending.error = error
        elif code:
            pending.code = code
        else:
            pending.error = "OAuth callback did not include a code."
        pending.event.set()
        body = (
            "<html><body><h1>Thomas sign-in complete</h1>"
            "<p>You can close this tab and return to Thomas.</p></body></html>"
        )
        return web.Response(text=body, content_type="text/html")


_CALLBACK_SERVER = _OAuthCallbackServer()


def register_openai_codex_routes(
    app: web.Application,
    *,
    require_api_access: Callable[[web.Request], None],
) -> None:
    async def api_status(request: web.Request) -> web.Response:
        require_api_access(request)
        profile = _profile_from_request(request)
        secrets = request.app[APP_SECRETS]
        token = read_openai_codex_token(secrets, profile) or import_local_codex_token(secrets, profile)
        payload = {
            "provider": OPENAI_CODEX_PROVIDER,
            "profile": profile,
            "base_url": OPENAI_CODEX_BASE_URL,
            **public_token_status(token),
            "needs_login": not has_openai_codex_token(secrets, profile),
        }
        return web.json_response(payload)

    async def api_login_start(request: web.Request) -> web.Response:
        require_api_access(request)
        payload = await _read_json_object(request)
        profile = _profile_from_request(request, payload)
        pending = await _CALLBACK_SERVER.start_flow(profile)
        open_browser = bool(payload.get("open_browser", True))
        if open_browser:
            asyncio.create_task(asyncio.to_thread(webbrowser.open, pending.flow.auth_url, new=2))
        return web.json_response(
            {
                "ok": True,
                "profile": profile,
                "state": pending.flow.state,
                "auth_url": pending.flow.auth_url,
                "callback_url": pending.flow.redirect_uri,
                "callback_bound": bool(pending.callback_bound),
                "expires_at": int(pending.flow.expires_at),
                "needs_paste": not pending.callback_bound,
            }
        )

    async def _exchange_pending(request: web.Request, pending: _PendingLogin, code: str) -> web.Response:
        secrets = request.app[APP_SECRETS]
        token_response = await exchange_code_for_tokens(
            code=code,
            code_verifier=pending.flow.code_verifier,
            redirect_uri=pending.flow.redirect_uri,
        )
        stored = write_openai_codex_token(secrets, pending.flow.profile, token_response, persist=True)
        _CALLBACK_SERVER.finish(pending.flow.state)
        return web.json_response(
            {
                "ok": True,
                "profile": pending.flow.profile,
                "already": False,
                **public_token_status(stored),
            }
        )

    async def api_login_complete(request: web.Request) -> web.Response:
        require_api_access(request)
        payload = await _read_json_object(request)
        redirect_url = str(payload.get("redirect_url") or payload.get("callback_url") or "").strip()
        code = str(payload.get("code") or "").strip()
        state = str(payload.get("state") or "").strip()
        if redirect_url:
            parsed_code, parsed_state = parse_oauth_callback(redirect_url)
            code = code or parsed_code
            state = state or parsed_state
        pending = _CALLBACK_SERVER.get_pending(state)
        if pending is None:
            raise web.HTTPBadRequest(text="unknown or expired OAuth state")
        if time.time() > float(pending.flow.expires_at):
            _CALLBACK_SERVER.finish(pending.flow.state)
            raise web.HTTPBadRequest(text="OAuth flow expired; start sign-in again")
        if not code:
            raise web.HTTPBadRequest(text="OAuth code is required")
        try:
            return await _exchange_pending(request, pending, code)
        # The exchange raises OpenAICodexOAuthError for every provider-side
        # refusal; the surrounding work is a secret-store write (OSError) and
        # response shaping (ValueError/TypeError/KeyError). Report the reason to
        # the sign-in UI instead of a bare 500 page.
        except (OpenAICodexOAuthError, OSError, ValueError, TypeError, KeyError) as e:
            log.warning("ChatGPT OAuth token exchange failed: %s", e)
            return web.json_response({"ok": False, "error": str(e), "profile": pending.flow.profile}, status=500)

    async def api_login(request: web.Request) -> web.Response:
        require_api_access(request)
        payload = await _read_json_object(request)
        profile = _profile_from_request(request, payload)
        secrets = request.app[APP_SECRETS]
        existing = read_openai_codex_token(secrets, profile)
        if public_token_status(existing)["logged_in"]:
            return web.json_response({"ok": True, "already": True, "profile": profile, **public_token_status(existing)})

        pending = await _CALLBACK_SERVER.start_flow(profile)
        asyncio.create_task(asyncio.to_thread(webbrowser.open, pending.flow.auth_url, new=2))
        timeout_s = max(5.0, min(float(payload.get("timeout_s") or 300.0), 900.0))
        try:
            await asyncio.wait_for(pending.event.wait(), timeout=timeout_s)
        except asyncio.TimeoutError:
            return web.json_response(
                {
                    "ok": False,
                    "pending": True,
                    "profile": profile,
                    "state": pending.flow.state,
                    "auth_url": pending.flow.auth_url,
                    "callback_url": pending.flow.redirect_uri,
                    "callback_bound": bool(pending.callback_bound),
                    "needs_paste": True,
                    "error": "Timed out waiting for ChatGPT sign-in callback. Paste the redirect URL to finish.",
                },
                status=202,
            )
        if pending.error:
            return web.json_response({"ok": False, "error": pending.error, "profile": profile}, status=500)
        try:
            return await _exchange_pending(request, pending, pending.code)
        except (OpenAICodexOAuthError, OSError, ValueError, TypeError, KeyError) as e:  # same set as login_complete
            log.warning("ChatGPT OAuth token exchange failed: %s", e)
            return web.json_response({"ok": False, "error": str(e), "profile": profile}, status=500)

    async def api_logout(request: web.Request) -> web.Response:
        require_api_access(request)
        payload = await _read_json_object(request)
        profile = _profile_from_request(request, payload)
        clear_openai_codex_token(request.app[APP_SECRETS], profile)
        return web.json_response({"ok": True, "profile": profile})

    async def api_models(request: web.Request) -> web.Response:
        require_api_access(request)
        profile = _profile_from_request(request)
        config: AppConfig = request.app[APP_CONFIG]
        return web.json_response({"profile": profile, "models": _configured_codex_models(config, profile)})

    async def on_cleanup(app_: web.Application) -> None:
        await _CALLBACK_SERVER.cleanup()

    app.router.add_get("/api/openai-codex/status", api_status)
    app.router.add_post("/api/openai-codex/login", api_login)
    app.router.add_post("/api/openai-codex/login/start", api_login_start)
    app.router.add_post("/api/openai-codex/login/complete", api_login_complete)
    app.router.add_post("/api/openai-codex/logout", api_logout)
    app.router.add_get("/api/openai-codex/models", api_models)
    app.on_cleanup.append(on_cleanup)
