"""Aiohttp bridge for webhook routes.

The canonical webhook logic currently lives in `thomas.server.routes.webhooks`
and is implemented with FastAPI-style handlers. Thomas serves via aiohttp, so
this bridge exposes equivalent aiohttp routes by adapting requests/responses.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Optional

from aiohttp import web
from fastapi import HTTPException as FastAPIHTTPException
from pydantic import ValidationError

from thomas.server.routes import webhooks as webhook_mod


@dataclass
class _ClientShim:
    host: str


class _FastAPIRequestShim:
    """Small shim for FastAPI request surface used by webhook handlers."""

    def __init__(self, *, body: bytes, remote_host: str) -> None:
        self._body = body
        self.client = _ClientShim(host=remote_host or "unknown")

    async def body(self) -> bytes:
        return self._body


def _to_plain_json(value: Any) -> Any:
    if hasattr(value, "model_dump") and callable(value.model_dump):
        return _to_plain_json(value.model_dump())
    if isinstance(value, dict):
        return {str(k): _to_plain_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_plain_json(v) for v in value]
    return value


def _json_response(payload: Any, *, status: int = 200) -> web.Response:
    return web.json_response(
        _to_plain_json(payload),
        status=int(status),
        dumps=lambda x: json.dumps(x, ensure_ascii=False),
    )


def _error_response(detail: Any, *, status: int) -> web.Response:
    return _json_response({"detail": detail}, status=status)


def _remote_host(request: web.Request) -> str:
    remote = str(request.remote or "").strip()
    if remote:
        return remote
    try:
        peer = request.transport.get_extra_info("peername") if request.transport else None
        if isinstance(peer, tuple) and peer:
            return str(peer[0] or "unknown")
    except Exception:
        pass
    return "unknown"


async def _read_json_object(request: web.Request) -> dict[str, Any]:
    try:
        raw = await request.read()
    except Exception as e:
        raise web.HTTPBadRequest(text=f"invalid json: {type(e).__name__}: {e}")
    if not raw:
        return {}
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except Exception as e:
        raise web.HTTPBadRequest(text=f"invalid json: {type(e).__name__}: {e}")
    if not isinstance(payload, dict):
        raise web.HTTPBadRequest(text="json body must be an object")
    return payload


async def _dispatch(handler: Callable[..., Any], *args: Any, **kwargs: Any) -> web.Response:
    try:
        result = await handler(*args, **kwargs)
        return _json_response(result)
    except FastAPIHTTPException as e:
        return _error_response(getattr(e, "detail", "request failed"), status=int(getattr(e, "status_code", 500)))
    except ValidationError as e:
        return _error_response(e.errors(), status=422)
    except Exception as e:
        status_code = getattr(e, "status_code", None)
        detail = getattr(e, "detail", None)
        if status_code is not None:
            try:
                return _error_response(detail if detail is not None else "request failed", status=int(status_code))
            except Exception:
                return _error_response("request failed", status=500)
        return _error_response("request failed", status=500)


def register_webhooks_routes(
    app: web.Application,
    *,
    require_api_access: Callable[[web.Request], None],
    signature_enforcement_default: bool | None = None,
) -> None:
    """Attach webhook management + receive routes to aiohttp app."""
    webhook_mod.configure_webhook_signature_enforcement_default(signature_enforcement_default)

    async def api_register(request: web.Request) -> web.Response:
        require_api_access(request)
        payload = await _read_json_object(request)
        try:
            body = webhook_mod.RegisterWebhookRequest(**payload)
        except (ValidationError, TypeError) as e:
            raise web.HTTPBadRequest(text=f"Invalid webhook registration payload: {e}")
        return await _dispatch(
            webhook_mod.register_webhook,
            body=body,
            x_admin_token=request.headers.get("X-Admin-Token"),
        )

    async def api_patch(request: web.Request) -> web.Response:
        require_api_access(request)
        payload = await _read_json_object(request)
        try:
            body = webhook_mod.PatchWebhookRequest(**payload)
        except (ValidationError, TypeError) as e:
            raise web.HTTPBadRequest(text=f"Invalid webhook patch payload: {e}")
        return await _dispatch(
            webhook_mod.patch_webhook,
            id=str(request.match_info.get("id") or "").strip(),
            body=body,
            x_admin_token=request.headers.get("X-Admin-Token"),
        )

    async def api_delete(request: web.Request) -> web.Response:
        require_api_access(request)
        return await _dispatch(
            webhook_mod.delete_webhook,
            id=str(request.match_info.get("id") or "").strip(),
            x_admin_token=request.headers.get("X-Admin-Token"),
        )

    async def api_list(request: web.Request) -> web.Response:
        require_api_access(request)
        return await _dispatch(
            webhook_mod.list_webhooks,
            x_admin_token=request.headers.get("X-Admin-Token"),
        )

    async def api_get(request: web.Request) -> web.Response:
        require_api_access(request)
        return await _dispatch(
            webhook_mod.get_webhook,
            id=str(request.match_info.get("id") or "").strip(),
            x_admin_token=request.headers.get("X-Admin-Token"),
        )

    async def api_stats_all(request: web.Request) -> web.Response:
        require_api_access(request)
        return await _dispatch(
            webhook_mod.stats_all,
            x_admin_token=request.headers.get("X-Admin-Token"),
        )

    async def api_inbox_recent(request: web.Request) -> web.Response:
        require_api_access(request)
        raw_limit = str(request.query.get("limit", "50")).strip()
        try:
            limit = int(raw_limit or "50")
        except Exception:
            return _error_response("limit must be an integer", status=400)
        return await _dispatch(
            webhook_mod.inbox_recent,
            limit=limit,
            x_admin_token=request.headers.get("X-Admin-Token"),
        )

    async def api_inbox_retry(request: web.Request) -> web.Response:
        require_api_access(request)
        return await _dispatch(
            webhook_mod.inbox_retry,
            event_id=str(request.match_info.get("event_id") or "").strip(),
            x_admin_token=request.headers.get("X-Admin-Token"),
        )

    async def api_test_webhook(request: web.Request) -> web.Response:
        require_api_access(request)
        payload = await _read_json_object(request)
        return await _dispatch(
            webhook_mod.test_webhook,
            id=str(request.match_info.get("id") or "").strip(),
            payload=payload,
            x_admin_token=request.headers.get("X-Admin-Token"),
        )

    async def receive_generic(request: web.Request) -> web.Response:
        body = await request.read()
        shim = _FastAPIRequestShim(body=body, remote_host=_remote_host(request))
        return await _dispatch(
            webhook_mod.receive_webhook,
            id=str(request.match_info.get("id") or "").strip(),
            request=shim,
            x_webhook_signature=request.headers.get("X-Webhook-Signature"),
            x_webhook_delivery=request.headers.get("X-Webhook-Delivery"),
        )

    async def receive_github(request: web.Request) -> web.Response:
        body = await request.read()
        shim = _FastAPIRequestShim(body=body, remote_host=_remote_host(request))
        return await _dispatch(
            webhook_mod.receive_github_webhook,
            request=shim,
            x_hub_signature_256=request.headers.get("X-Hub-Signature-256"),
            x_github_event=request.headers.get("X-GitHub-Event"),
            x_github_delivery=request.headers.get("X-GitHub-Delivery"),
        )

    async def receive_stripe(request: web.Request) -> web.Response:
        body = await request.read()
        shim = _FastAPIRequestShim(body=body, remote_host=_remote_host(request))
        return await _dispatch(
            webhook_mod.receive_stripe_webhook,
            request=shim,
            stripe_signature=request.headers.get("Stripe-Signature"),
        )

    # Management endpoints (loopback-only or remote-token via require_api_access).
    app.router.add_post("/api/webhooks/register", api_register)
    app.router.add_get("/api/webhooks/stats/all", api_stats_all)
    app.router.add_get("/api/webhooks/inbox/recent", api_inbox_recent)
    app.router.add_post("/api/webhooks/inbox/retry/{event_id}", api_inbox_retry)
    app.router.add_post("/api/webhooks/test/{id}", api_test_webhook)
    app.router.add_patch("/api/webhooks/{id}", api_patch)
    app.router.add_delete("/api/webhooks/{id}", api_delete)
    app.router.add_get("/api/webhooks/{id}", api_get)
    app.router.add_get("/api/webhooks", api_list)

    # Public provider receivers.
    app.router.add_post("/webhooks/receive/github", receive_github)
    app.router.add_post("/webhooks/receive/stripe", receive_stripe)
    app.router.add_post("/webhooks/receive/{id}", receive_generic)
