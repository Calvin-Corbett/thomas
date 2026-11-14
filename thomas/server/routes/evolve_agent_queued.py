"""What Build answers when a message arrives while a run is going, or while this computer is full.

Build's composer sends ``queue_if_busy``. The route then accepts the message instead of refusing it: ``202`` with
``queued`` when the conversation's own run is still going (the composer holds it and sends it when that run is
saved), or ``202`` with ``waiting_for_slot`` when every run slot is taken (the composer asks again shortly). A
caller that does not send ``queue_if_busy`` -- Autopilot, Praxis intake -- keeps the ``409`` it branches on.
"""

from __future__ import annotations

from typing import Any

from aiohttp import web

WAIT_RETRY_S = 5


def busy_answer(body: dict[str, Any], code: str, error: str, *, full: bool = False) -> web.Response:
    """The reply to a send that cannot start now: queued or waiting for the composer, the 409 guard for other callers.

    ``full`` means every run slot (or the memory for one) is taken, so the person's message is not behind this
    conversation's own run but behind the machine."""
    if not body.get("queue_if_busy"):
        return web.json_response({"ok": False, "error": error, "code": code}, status=409)
    if full:
        answer = {"waiting_for_slot": True, "notice": "Waiting for a free slot", "retry_after_s": WAIT_RETRY_S}
    else:
        answer = {"queued": True, "notice": "Queued, runs next", "retry_after_s": WAIT_RETRY_S}
    return web.json_response({"ok": True, "code": code, "reason": error, **answer}, status=202)
