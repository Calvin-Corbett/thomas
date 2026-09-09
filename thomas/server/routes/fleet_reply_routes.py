"""HTTP API for inline reply/steer from the fleet dashboard (CAP-040).

This is the route layer over :mod:`thomas.agent.fleet_reply`. The dashboard
renders one row per live fleet session with a free-text box; typing a steer and
hitting send POSTs here, and the JSON receipt this module returns is exactly the
*delivery acknowledgement* the row renders inline (``delivered`` / ``acked``, or
``failed`` + ``undelivered``).

Architecture: server -> agent only. ``FleetReplyService`` owns all state; this
module holds a single process-wide instance (``get_fleet_reply_service``) so the
list / dispatch / ack / receipt routes share one registry, and tests can inject a
hermetic service with a fake clock and fake channels.

Routes
------
``GET    /api/fleet/reply/sessions``                    live sessions + receipt rollup
``POST   /api/fleet/reply/sessions``                    register a live session
``DELETE /api/fleet/reply/sessions/{session_id}``       mark a session ended
``POST   /api/fleet/reply/sessions/{session_id}/reply`` free-text steer -> receipt
``POST   /api/fleet/reply/receipts/{receipt_id}/ack``   session confirms receipt
``GET    /api/fleet/reply/receipts``                    receipts (``?session_id=``)

Error contract (never a 500 for user error):
    400 empty/missing reply text or session id
    404 unknown/ended session, unknown receipt id
    409 ack attempted from an incompatible receipt state (e.g. already failed)
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from aiohttp import web

from thomas.agent.fleet_reply import (
    DeliveryReceipt,
    FleetReplyConfig,
    FleetReplyService,
    ReceiptStateError,
    UnknownReceiptError,
    UnknownSessionError,
)

log = logging.getLogger(__name__)

__all__ = [
    "build_fleet_reply_handlers",
    "get_fleet_reply_service",
    "register_fleet_reply_routes",
    "reset_fleet_reply_service",
    "set_fleet_reply_service",
]

# Bodies larger than this are rejected before parsing -- a steer is a sentence,
# not a payload dump.
MAX_REPLY_TEXT_CHARS = 8000

# Concrete faults from decoding a request body. A WIDE SPECIFIC tuple on
# purpose: a bare ``except Exception`` would swallow real programming errors.
_BODY_FAULTS: tuple[type[BaseException], ...] = (
    json.JSONDecodeError,
    ValueError,
    TypeError,
    UnicodeDecodeError,
)

_SERVICE: FleetReplyService | None = None


# --------------------------------------------------------------------------- #
# module-level service singleton
# --------------------------------------------------------------------------- #
def get_fleet_reply_service() -> FleetReplyService:
    """Return the process-wide reply service, creating it on first use."""
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = FleetReplyService(config=FleetReplyConfig())
    return _SERVICE


def set_fleet_reply_service(service: FleetReplyService) -> FleetReplyService:
    """Install an explicit service instance (used at wiring time and by tests)."""
    global _SERVICE
    _SERVICE = service
    return _SERVICE


def reset_fleet_reply_service() -> None:
    """Drop the singleton so the next accessor call builds a fresh service."""
    global _SERVICE
    _SERVICE = None


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
async def _json_body(request: web.Request) -> dict[str, Any]:
    """Parse a JSON object body; a malformed/absent body reads as empty."""
    try:
        body = await request.json()
    except _BODY_FAULTS as exc:
        log.debug("fleet reply: unparseable request body (%s)", exc)
        return {}
    return body if isinstance(body, dict) else {}


def _receipt_payload(receipt: DeliveryReceipt) -> dict[str, Any]:
    """JSON view of a receipt -- this IS the delivery acknowledgement the UI renders."""
    return {
        "id": receipt.id,
        "session_id": receipt.session_id,
        "text": receipt.text,
        "seq": receipt.seq,
        "state": receipt.state.value,
        "queued_at": receipt.queued_at,
        "delivered_at": receipt.delivered_at,
        "acked_at": receipt.acked_at,
        "failed_at": receipt.failed_at,
        "reason": receipt.reason,
        "undelivered": bool(receipt.undelivered),
        "terminal": bool(receipt.is_terminal),
        "acknowledged": bool(receipt.is_acked),
        "delivered": receipt.delivered_at is not None,
        "failed": bool(receipt.is_failed),
    }


def _session_payload(service: FleetReplyService, session_id: str) -> dict[str, Any]:
    receipts = service.receipts(session_id)
    last = receipts[-1] if receipts else None
    return {
        "id": session_id,
        "live": True,
        "reply_count": len(receipts),
        "pending_count": sum(1 for r in receipts if not r.is_terminal),
        "acked_count": sum(1 for r in receipts if r.is_acked),
        "failed_count": sum(1 for r in receipts if r.is_failed),
        "last_receipt": _receipt_payload(last) if last is not None else None,
    }


def _clean_text(raw: object) -> str:
    return raw.strip() if isinstance(raw, str) else ""


# --------------------------------------------------------------------------- #
# handler factory
# --------------------------------------------------------------------------- #
def build_fleet_reply_handlers(
    app: web.Application,
    *,
    require_api_access: Callable[[web.Request], None] | None = None,
    service_resolver: Callable[[], FleetReplyService] = get_fleet_reply_service,
) -> dict[str, Any]:
    """Build the fleet-reply handlers as a name->handler map."""

    def _guard(request: web.Request) -> None:
        if callable(require_api_access):
            require_api_access(request)

    def _service() -> FleetReplyService:
        return service_resolver()

    async def list_sessions(request: web.Request) -> web.Response:
        _guard(request)
        service = _service()
        # Deadline reconciliation first, so a steer that was never acked shows
        # up in the dashboard as failed/undelivered rather than stuck "queued".
        timed_out = service.reconcile()
        sessions = [_session_payload(service, sid) for sid in sorted(service.session_ids())]
        return web.json_response(
            {
                "ok": True,
                "sessions": sessions,
                "count": len(sessions),
                "timed_out": [_receipt_payload(r) for r in timed_out],
            }
        )

    async def register_session(request: web.Request) -> web.Response:
        _guard(request)
        body = await _json_body(request)
        session_id = _clean_text(body.get("session_id") or body.get("id"))
        if not session_id:
            return web.json_response({"ok": False, "error": "missing session_id"}, status=400)
        service = _service()
        service.register_session(session_id)
        return web.json_response({"ok": True, "session": _session_payload(service, session_id)})

    async def unregister_session(request: web.Request) -> web.Response:
        _guard(request)
        session_id = str(request.match_info.get("session_id", ""))
        existed = _service().unregister_session(session_id)
        if not existed:
            return web.json_response(
                {"ok": False, "error": f"unknown fleet session {session_id!r}", "session_id": session_id},
                status=404,
            )
        return web.json_response({"ok": True, "session_id": session_id, "live": False})

    async def send_reply(request: web.Request) -> web.Response:
        _guard(request)
        session_id = str(request.match_info.get("session_id", "")).strip()
        body = await _json_body(request)
        text = _clean_text(body.get("text") or body.get("reply") or body.get("message"))
        if not session_id:
            return web.json_response({"ok": False, "error": "missing session_id"}, status=400)
        if not text:
            return web.json_response(
                {"ok": False, "error": "reply text must not be empty", "session_id": session_id},
                status=400,
            )
        if len(text) > MAX_REPLY_TEXT_CHARS:
            return web.json_response(
                {
                    "ok": False,
                    "error": f"reply text exceeds {MAX_REPLY_TEXT_CHARS} characters",
                    "session_id": session_id,
                },
                status=400,
            )
        service = _service()
        try:
            receipt = service.dispatch_reply(session_id, text)
        except UnknownSessionError as exc:
            # Ended / never-registered session: a clear 4xx, never a silent drop
            # and never a 500.
            return web.json_response(
                {"ok": False, "error": str(exc), "session_id": session_id, "reason": "unknown_session"},
                status=404,
            )
        except ValueError as exc:
            return web.json_response(
                {"ok": False, "error": str(exc), "session_id": session_id},
                status=400,
            )
        payload = _receipt_payload(receipt)
        return web.json_response({"ok": not receipt.is_failed, "receipt": payload, "acknowledgement": payload})

    async def ack_receipt(request: web.Request) -> web.Response:
        _guard(request)
        receipt_id = str(request.match_info.get("receipt_id", "")).strip()
        if not receipt_id:
            return web.json_response({"ok": False, "error": "missing receipt_id"}, status=400)
        service = _service()
        try:
            receipt = service.acknowledge(receipt_id)
        except UnknownReceiptError as exc:
            return web.json_response(
                {"ok": False, "error": str(exc), "receipt_id": receipt_id, "reason": "unknown_receipt"},
                status=404,
            )
        except ReceiptStateError as exc:
            return web.json_response(
                {"ok": False, "error": str(exc), "receipt_id": receipt_id, "reason": "bad_state"},
                status=409,
            )
        payload = _receipt_payload(receipt)
        return web.json_response({"ok": True, "receipt": payload, "acknowledgement": payload})

    async def list_receipts(request: web.Request) -> web.Response:
        _guard(request)
        session_id = str(request.query.get("session_id", "")).strip() or None
        service = _service()
        service.reconcile()
        receipts = service.receipts(session_id)
        return web.json_response(
            {
                "ok": True,
                "session_id": session_id,
                "receipts": [_receipt_payload(r) for r in receipts],
                "count": len(receipts),
            }
        )

    return {
        "list_sessions": list_sessions,
        "register_session": register_session,
        "unregister_session": unregister_session,
        "send_reply": send_reply,
        "ack_receipt": ack_receipt,
        "list_receipts": list_receipts,
    }


def register_fleet_reply_routes(
    app: web.Application,
    config: object | None = None,
    *,
    require_api_access: Callable[[web.Request], None] | None = None,
    service_resolver: Callable[[], FleetReplyService] = get_fleet_reply_service,
) -> None:
    """Register the fleet inline-reply API onto the aiohttp app."""
    handlers = build_fleet_reply_handlers(
        app,
        require_api_access=require_api_access,
        service_resolver=service_resolver,
    )
    app.router.add_get("/api/fleet/reply/sessions", handlers["list_sessions"])
    app.router.add_post("/api/fleet/reply/sessions", handlers["register_session"])
    app.router.add_delete("/api/fleet/reply/sessions/{session_id}", handlers["unregister_session"])
    app.router.add_post("/api/fleet/reply/sessions/{session_id}/reply", handlers["send_reply"])
    app.router.add_post("/api/fleet/reply/receipts/{receipt_id}/ack", handlers["ack_receipt"])
    app.router.add_get("/api/fleet/reply/receipts", handlers["list_receipts"])
