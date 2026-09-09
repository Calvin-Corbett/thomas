"""HTTP API for the Paper Trading workspace.

Surface: ``/api/plugins/paper-trading/*``. The model drives the same engine via
agent tools; this route backs the UI and — critically — owns the human approval
gate (`POST .../proposals/{id}/approve`), which is the only path that can promote
a proposal to ``approved`` and optionally submit it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Callable

from aiohttp import web

from thomas.server.app_keys import (
    APP_CONFIG,
    APP_LOCAL_STEP_UP_AUTH_PROVIDER,
    APP_MEMORY,
)

_log = logging.getLogger(__name__)

_PLUGIN_ID = "paper-trading"
_PLUGIN_RELATIVE = Path(".thomas") / "plugins" / "paper-trading"


def _data_dir(app: web.Application) -> Path:
    config = app[APP_CONFIG]
    return Path(config.memory.root_path) / _PLUGIN_RELATIVE


def _memory(app: web.Application) -> Any:
    try:
        return app.get(APP_MEMORY)
    # A keyed lookup on the app mapping: KeyError/TypeError if the key was never
    # installed or is not the AppKey type this aiohttp version expects.
    except (KeyError, TypeError, AttributeError):
        return None


def _engine(app: web.Application):
    from thomas.marketplace.paper_trading.engine import PaperTradingEngine

    return PaperTradingEngine.build(data_dir=_data_dir(app), memory_engine=_memory(app))


def _require_enabled(app: web.Application) -> None:
    config = app[APP_CONFIG]
    try:
        from thomas.server.desktop_plugins import is_plugin_enabled
    except ImportError:
        return  # if the gate module is unavailable, don't hard-fail the route
    if not is_plugin_enabled(config, _PLUGIN_ID):
        raise web.HTTPNotFound(text="Paper Trading is not installed or enabled")


async def _json_body(request: web.Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
        # A body that will not decode is treated as no body at all.
        return {}
    return payload if isinstance(payload, dict) else {}


def _human_auth_required() -> bool:
    raw = os.environ.get("THOMAS_PAPER_TRADING_DEV_ALLOW_UNVERIFIED", "")
    return raw.strip().lower() not in {"1", "true", "yes", "on"}


def _default_step_up_provider():
    """Build the platform-native step-up auth provider on demand.

    The application does not install APP_LOCAL_STEP_UP_AUTH_PROVIDER at boot, so
    we build it here. ``build_local_step_up_auth_provider`` returns the real
    Windows/macOS/Linux native-auth provider (or an Unsupported one that denies),
    which is what makes the human gate actually function in production.
    """
    try:
        from thomas.marketplace.security.third_party_access import (
            build_local_step_up_auth_provider,
        )

        return build_local_step_up_auth_provider()
    # Building the platform provider touches an optional import and the native
    # auth stack: ImportError when the security module is absent, OSError when
    # the OS credential API cannot be reached, and RuntimeError/AttributeError/
    # TypeError/ValueError when this platform has no usable implementation.
    # None here means "no human gate available", which the caller fails closed on.
    except (ImportError, OSError, RuntimeError, AttributeError, TypeError, ValueError):
        _log.warning("paper-trading: local step-up auth provider unavailable", exc_info=True)
        return None


async def _require_human_step_up(app: web.Application, *, action: str, reason: str) -> str:
    """Require a native step-up auth (Windows Hello / OS credential prompt).

    This is the REAL human gate. ``require_api_access`` only proves the request
    came from loopback — but Thomas's own agent runs on that loopback with shell
    and browser tools, so it could curl/click the approve endpoint itself. A
    native auth prompt is something the in-process agent provably cannot forge.
    Returns a verified approver identity; raises HTTPForbidden otherwise.
    """
    try:
        provider = app.get(APP_LOCAL_STEP_UP_AUTH_PROVIDER)
    # Same keyed-lookup faults as _memory(): the provider is simply not installed.
    except (KeyError, TypeError, AttributeError):
        provider = None
    if provider is None:
        # Not installed at boot -> build the native provider on demand.
        provider = _default_step_up_provider()

    if provider is None:
        if not _human_auth_required():
            _log.warning(
                "paper-trading approval bypass active "
                "(THOMAS_PAPER_TRADING_DEV_ALLOW_UNVERIFIED) — approval is NOT "
                "human-verified; intended for dev/test only"
            )
            return "dev-unverified"
        raise web.HTTPForbidden(
            text="Approval requires local step-up authentication, which is unavailable in this environment."
        )
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, provider.authorize, action, reason)
    # The native prompt is an OS call behind ctypes/subprocess: OSError for the
    # syscall, RuntimeError for a provider that cannot run here, and
    # AttributeError/TypeError/ValueError for a provider that does not implement
    # the authorize() contract. Every one of them denies -- this gate fails closed.
    except (OSError, RuntimeError, AttributeError, TypeError, ValueError) as exc:
        _log.warning("paper-trading: local step-up authorization failed", exc_info=True)
        raise web.HTTPForbidden(text=f"Local authorization failed: {exc}") from exc
    if not getattr(result, "authorized", False):
        code = getattr(result, "error_code", None) or "denied"
        raise web.HTTPForbidden(text=f"Local authorization not granted ({code}).")
    return f"local-step-up:{getattr(result, 'method', 'verified')}"


def register_paper_trading_routes(
    app: web.Application,
    *,
    require_api_access: Callable[[web.Request], Any],
) -> None:
    """Register all paper-trading HTTP routes onto ``app``."""

    def guard(request: web.Request) -> None:
        require_api_access(request)
        _require_enabled(request.app)

    async def bootstrap(request: web.Request) -> web.Response:
        guard(request)
        data = await _engine(request.app).bootstrap()
        return web.json_response(data)

    async def account(request: web.Request) -> web.Response:
        guard(request)
        acct = await _engine(request.app).account()
        return web.json_response(acct.to_dict())

    async def positions(request: web.Request) -> web.Response:
        guard(request)
        rows = await _engine(request.app).positions()
        return web.json_response([p.to_dict() for p in rows])

    async def quote(request: web.Request) -> web.Response:
        guard(request)
        symbol = (request.query.get("symbol") or "").strip()
        if not symbol:
            raise web.HTTPBadRequest(text="symbol query param is required")
        q = await _engine(request.app).quote(symbol)
        return web.json_response(q.to_dict())

    async def bars(request: web.Request) -> web.Response:
        guard(request)
        symbol = (request.query.get("symbol") or "").strip()
        if not symbol:
            raise web.HTTPBadRequest(text="symbol query param is required")
        timeframe = (request.query.get("timeframe") or "1Day").strip()
        try:
            limit = int(request.query.get("limit") or 30)
        except ValueError:
            limit = 30
        rows = await _engine(request.app).bars(symbol, timeframe=timeframe, limit=limit)
        return web.json_response({"symbol": symbol.upper(), "bars": rows})

    async def list_proposals(request: web.Request) -> web.Response:
        guard(request)
        status = (request.query.get("status") or "").strip() or None
        rows = _engine(request.app).store.list_proposals(status=status)
        return web.json_response([p.to_dict() for p in rows])

    async def create_proposal(request: web.Request) -> web.Response:
        guard(request)
        body = await _json_body(request)
        symbol = str(body.get("symbol") or "").strip()
        side = str(body.get("side") or "").lower().strip()
        thesis = str(body.get("thesis") or "").strip()
        invalidation = str(body.get("invalidation") or "").strip()
        if not symbol or side not in {"buy", "sell"}:
            raise web.HTTPBadRequest(text="symbol and side (buy/sell) are required")
        if not thesis or not invalidation:
            raise web.HTTPBadRequest(text="thesis and invalidation are required")
        from thomas.marketplace.paper_trading._exceptions import PaperTradingError

        try:
            proposal = await _engine(request.app).propose(
                symbol=symbol,
                side=side,
                thesis=thesis,
                invalidation=invalidation,
                qty=body.get("qty"),
                notional=body.get("notional"),
                order_type=str(body.get("order_type") or "market").lower(),
                limit_price=body.get("limit_price"),
                time_in_force=str(body.get("time_in_force") or "day").lower(),
            )
        except PaperTradingError as exc:
            raise web.HTTPBadRequest(text=str(exc))
        return web.json_response(proposal.to_dict(), status=201)

    async def approve_proposal(request: web.Request) -> web.Response:
        # THE HUMAN GATE: a native step-up auth tap (Windows Hello / OS credential
        # prompt) that the in-process agent cannot forge. The approver identity is
        # derived from that verified result, NOT from the request body.
        guard(request)
        proposal_id = request.match_info["proposal_id"]
        body = await _json_body(request)
        from thomas.marketplace.paper_trading._exceptions import (
            ApprovalRequired,
            BrokerError,
            ProposalNotFound,
            RiskRejected,
        )

        approver = await _require_human_step_up(
            request.app,
            action="paper_trading.approve",
            reason=f"Approve and submit paper trade {proposal_id}",
        )
        engine = _engine(request.app)
        try:
            proposal = engine.approve(proposal_id, approver=approver)
            if body.get("submit"):
                proposal = await engine.submit(proposal_id)
        except ProposalNotFound:
            raise web.HTTPNotFound(text="proposal not found")
        except (ApprovalRequired, RiskRejected) as exc:
            raise web.HTTPConflict(text=str(exc))
        except BrokerError as exc:
            raise web.HTTPBadGateway(text=str(exc))
        return web.json_response(proposal.to_dict())

    async def reject_proposal(request: web.Request) -> web.Response:
        guard(request)
        proposal_id = request.match_info["proposal_id"]
        body = await _json_body(request)
        from thomas.marketplace.paper_trading._exceptions import (
            ApprovalRequired,
            ProposalNotFound,
        )

        try:
            proposal = _engine(request.app).reject(proposal_id, note=str(body.get("note") or ""))
        except ProposalNotFound:
            raise web.HTTPNotFound(text="proposal not found")
        except ApprovalRequired as exc:
            raise web.HTTPConflict(text=str(exc))
        return web.json_response(proposal.to_dict())

    async def submit_proposal(request: web.Request) -> web.Response:
        guard(request)
        proposal_id = request.match_info["proposal_id"]
        from thomas.marketplace.paper_trading._exceptions import (
            ApprovalRequired,
            BrokerError,
            ProposalNotFound,
            RiskRejected,
        )

        try:
            proposal = await _engine(request.app).submit(proposal_id)
        except ProposalNotFound:
            raise web.HTTPNotFound(text="proposal not found")
        except (ApprovalRequired, RiskRejected) as exc:
            raise web.HTTPConflict(text=str(exc))
        except BrokerError as exc:
            raise web.HTTPBadGateway(text=str(exc))
        return web.json_response(proposal.to_dict())

    async def reconcile(request: web.Request) -> web.Response:
        guard(request)
        engine = _engine(request.app)
        entries = await engine.reconcile()
        return web.json_response({"updated": [e.to_dict() for e in entries], "review": engine.review()})

    async def track_record(request: web.Request) -> web.Response:
        guard(request)
        return web.json_response(_engine(request.app).review())

    async def recall(request: web.Request) -> web.Response:
        guard(request)
        symbol = (request.query.get("symbol") or "").strip()
        return web.json_response(_engine(request.app).recall(symbol))

    async def credentials_status(request: web.Request) -> web.Response:
        guard(request)
        cfg = _engine(request.app).config
        return web.json_response({"has_credentials": cfg.has_credentials, "simulated": not cfg.has_credentials})

    async def set_credentials(request: web.Request) -> web.Response:
        guard(request)
        body = await _json_body(request)
        key_id = str(body.get("key_id") or "").strip()
        secret_key = str(body.get("secret_key") or "").strip()
        if not key_id or not secret_key:
            raise web.HTTPBadRequest(text="key_id and secret_key are required")
        from thomas.marketplace.paper_trading.config import write_credentials_file

        write_credentials_file(_data_dir(request.app), key_id, secret_key)
        return web.json_response({"ok": True, "has_credentials": True})

    base = f"/api/plugins/{_PLUGIN_ID}"
    app.router.add_get(f"{base}/bootstrap", bootstrap)
    app.router.add_get(f"{base}/account", account)
    app.router.add_get(f"{base}/positions", positions)
    app.router.add_get(f"{base}/quote", quote)
    app.router.add_get(f"{base}/bars", bars)
    app.router.add_get(f"{base}/proposals", list_proposals)
    app.router.add_post(f"{base}/proposals", create_proposal)
    app.router.add_post(f"{base}/proposals/{{proposal_id}}/approve", approve_proposal)
    app.router.add_post(f"{base}/proposals/{{proposal_id}}/reject", reject_proposal)
    app.router.add_post(f"{base}/proposals/{{proposal_id}}/submit", submit_proposal)
    app.router.add_post(f"{base}/reconcile", reconcile)
    app.router.add_get(f"{base}/track-record", track_record)
    app.router.add_get(f"{base}/recall", recall)
    app.router.add_get(f"{base}/credentials/status", credentials_status)
    app.router.add_post(f"{base}/credentials", set_credentials)
