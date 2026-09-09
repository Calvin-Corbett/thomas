"""CAP-040 route acceptance: inline free-text reply/steer from the fleet dashboard.

Exercises the HTTP layer registered by
``thomas.server.routes.fleet_reply_routes.register_fleet_reply_routes`` through a
real aiohttp ``TestClient`` (the idiom used by ``tests/prompt_pack``), with a
hermetic ``FleetReplyService`` injected via ``service_resolver`` -- fake clock,
in-memory fake channels, no network, no temp state.

Proves the acceptance line end-to-end over HTTP:
  * sending a free-text reply to a LIVE session returns a delivery
    acknowledgement (receipt ``delivered``) and acking it flips it to ``acked``;
  * a reply to an UNKNOWN/ended session is a clear 404 -- not a 500, not a
    silent drop;
  * empty / whitespace / oversized reply text is a 400;
  * a refusing channel yields a ``failed`` + ``undelivered`` acknowledgement
    rather than an error page;
  * an un-acked reply past the ack deadline shows up reconciled as failed;
  * receipts are listable per session in dispatch order.
"""

from __future__ import annotations

import asyncio

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.agent.fleet_reply import (
    FleetReplyConfig,
    FleetReplyService,
    ReplyEnvelope,
)
from thomas.server.routes.fleet_reply_routes import (
    MAX_REPLY_TEXT_CHARS,
    get_fleet_reply_service,
    register_fleet_reply_routes,
    reset_fleet_reply_service,
    set_fleet_reply_service,
)

REPLY_URL = "/api/fleet/reply/sessions/{sid}/reply"
ACK_URL = "/api/fleet/reply/receipts/{rid}/ack"


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def __call__(self) -> float:
        return self.now


class FakeChannel:
    """Hermetic in-memory channel: records envelopes, optionally refuses/raises."""

    def __init__(self, *, accept: bool = True, raises: BaseException | None = None) -> None:
        self.accept = accept
        self.raises = raises
        self.delivered: list[ReplyEnvelope] = []

    def deliver(self, envelope: ReplyEnvelope) -> bool:
        if self.raises is not None:
            raise self.raises
        self.delivered.append(envelope)
        return self.accept


def _build(service: FleetReplyService) -> web.Application:
    app = web.Application()
    register_fleet_reply_routes(app, None, service_resolver=lambda: service)
    return app


def _service(*, ack_deadline: float = 30.0, clock: FakeClock | None = None) -> FleetReplyService:
    return FleetReplyService(
        config=FleetReplyConfig(ack_deadline_seconds=ack_deadline),
        clock=clock or FakeClock(),
    )


def _run(coro_factory) -> None:
    """Run an async test body that receives a started TestClient."""

    async def runner() -> None:
        service, body = coro_factory()
        client = TestClient(TestServer(_build(service)))
        await client.start_server()
        try:
            await body(client, service)
        finally:
            await client.close()

    asyncio.run(runner())


# --------------------------------------------------------------------------- #
# acceptance: live session -> delivery acknowledgement
# --------------------------------------------------------------------------- #
def test_free_text_reply_to_live_session_returns_delivery_acknowledgement() -> None:
    def setup():
        service = _service()
        channel = FakeChannel()
        service.register_session("sess-alpha", channel)

        async def body(client: TestClient, svc: FleetReplyService) -> None:
            resp = await client.post(REPLY_URL.format(sid="sess-alpha"), json={"text": "focus on the failing test"})
            assert resp.status == 200
            payload = await resp.json()
            assert payload["ok"] is True
            receipt = payload["receipt"]
            # the acknowledgement mirror the UI renders inline on the row
            assert payload["acknowledgement"] == receipt
            assert receipt["state"] == "delivered"
            assert receipt["delivered"] is True
            assert receipt["acknowledged"] is False
            assert receipt["undelivered"] is False
            assert receipt["session_id"] == "sess-alpha"
            assert receipt["text"] == "focus on the failing test"
            assert receipt["id"].startswith("rcpt-")
            # the free text actually reached the channel
            assert [e.text for e in channel.delivered] == ["focus on the failing test"]

        return service, body

    _run(setup)


def test_ack_transitions_receipt_to_acked_over_http() -> None:
    def setup():
        service = _service()
        service.register_session("sess-alpha", FakeChannel())

        async def body(client: TestClient, svc: FleetReplyService) -> None:
            sent = await (await client.post(REPLY_URL.format(sid="sess-alpha"), json={"text": "steer me"})).json()
            receipt_id = sent["receipt"]["id"]

            resp = await client.post(ACK_URL.format(rid=receipt_id))
            assert resp.status == 200
            acked = (await resp.json())["receipt"]
            assert acked["state"] == "acked"
            assert acked["acknowledged"] is True
            assert acked["terminal"] is True
            assert acked["acked_at"] is not None

            # idempotent re-ack stays 200/acked
            again = await client.post(ACK_URL.format(rid=receipt_id))
            assert again.status == 200
            assert (await again.json())["receipt"]["state"] == "acked"

        return service, body

    _run(setup)


# --------------------------------------------------------------------------- #
# acceptance: unknown session is a clear 4xx, never a crash
# --------------------------------------------------------------------------- #
def test_reply_to_unknown_session_is_404_not_a_crash() -> None:
    def setup():
        service = _service()
        service.register_session("sess-alpha", FakeChannel())

        async def body(client: TestClient, svc: FleetReplyService) -> None:
            resp = await client.post(REPLY_URL.format(sid="sess-ghost"), json={"text": "hello?"})
            assert resp.status == 404
            payload = await resp.json()
            assert payload["ok"] is False
            assert payload["reason"] == "unknown_session"
            assert "sess-ghost" in payload["error"]
            # nothing was recorded for the ghost session
            assert svc.receipts("sess-ghost") == ()

        return service, body

    _run(setup)


def test_reply_to_ended_session_is_404_after_unregister() -> None:
    def setup():
        service = _service()
        service.register_session("sess-ending", FakeChannel())

        async def body(client: TestClient, svc: FleetReplyService) -> None:
            gone = await client.delete("/api/fleet/reply/sessions/sess-ending")
            assert gone.status == 200
            assert (await gone.json())["live"] is False

            resp = await client.post(REPLY_URL.format(sid="sess-ending"), json={"text": "still there?"})
            assert resp.status == 404
            assert (await resp.json())["reason"] == "unknown_session"

            # deleting a session that is already gone is also a clean 404
            twice = await client.delete("/api/fleet/reply/sessions/sess-ending")
            assert twice.status == 404

        return service, body

    _run(setup)


def test_ack_of_unknown_receipt_is_404() -> None:
    def setup():
        service = _service()

        async def body(client: TestClient, svc: FleetReplyService) -> None:
            resp = await client.post(ACK_URL.format(rid="rcpt-nope"))
            assert resp.status == 404
            payload = await resp.json()
            assert payload["ok"] is False
            assert payload["reason"] == "unknown_receipt"

        return service, body

    _run(setup)


def test_ack_of_failed_receipt_is_409_not_500() -> None:
    def setup():
        clock = FakeClock()
        service = _service(ack_deadline=10.0, clock=clock)
        service.register_session("sess-slow", FakeChannel())

        async def body(client: TestClient, svc: FleetReplyService) -> None:
            sent = await (await client.post(REPLY_URL.format(sid="sess-slow"), json={"text": "steer"})).json()
            receipt_id = sent["receipt"]["id"]
            clock.advance(11.0)
            # listing reconciles the deadline -> receipt fails, undelivered
            listed = await (await client.get("/api/fleet/reply/receipts?session_id=sess-slow")).json()
            assert listed["receipts"][0]["state"] == "failed"
            assert listed["receipts"][0]["undelivered"] is True
            assert listed["receipts"][0]["reason"] == "ack_timeout"

            resp = await client.post(ACK_URL.format(rid=receipt_id))
            assert resp.status == 409
            assert (await resp.json())["reason"] == "bad_state"

        return service, body

    _run(setup)


# --------------------------------------------------------------------------- #
# input validation: 4xx, never 500
# --------------------------------------------------------------------------- #
def test_empty_and_whitespace_reply_text_is_400() -> None:
    def setup():
        service = _service()
        service.register_session("sess-alpha", FakeChannel())

        async def body(client: TestClient, svc: FleetReplyService) -> None:
            for payload in ({"text": ""}, {"text": "   \n\t "}, {}):
                resp = await client.post(REPLY_URL.format(sid="sess-alpha"), json=payload)
                assert resp.status == 400, payload
                assert (await resp.json())["ok"] is False
            assert svc.receipts("sess-alpha") == ()

        return service, body

    _run(setup)


def test_malformed_json_body_is_400_not_500() -> None:
    def setup():
        service = _service()
        service.register_session("sess-alpha", FakeChannel())

        async def body(client: TestClient, svc: FleetReplyService) -> None:
            resp = await client.post(
                REPLY_URL.format(sid="sess-alpha"),
                data="{not json",
                headers={"Content-Type": "application/json"},
            )
            assert resp.status == 400
            assert (await resp.json())["ok"] is False

        return service, body

    _run(setup)


def test_oversized_reply_text_is_400() -> None:
    def setup():
        service = _service()
        service.register_session("sess-alpha", FakeChannel())

        async def body(client: TestClient, svc: FleetReplyService) -> None:
            resp = await client.post(
                REPLY_URL.format(sid="sess-alpha"),
                json={"text": "x" * (MAX_REPLY_TEXT_CHARS + 1)},
            )
            assert resp.status == 400
            assert "exceeds" in (await resp.json())["error"]

        return service, body

    _run(setup)


def test_register_session_requires_a_session_id() -> None:
    def setup():
        service = _service()

        async def body(client: TestClient, svc: FleetReplyService) -> None:
            resp = await client.post("/api/fleet/reply/sessions", json={"session_id": "  "})
            assert resp.status == 400
            assert (await resp.json())["error"] == "missing session_id"

        return service, body

    _run(setup)


# --------------------------------------------------------------------------- #
# failure acknowledgement (undelivered) still renders as a receipt
# --------------------------------------------------------------------------- #
def test_refusing_channel_yields_failed_undelivered_acknowledgement() -> None:
    def setup():
        service = _service()
        service.register_session("sess-closing", FakeChannel(accept=False))

        async def body(client: TestClient, svc: FleetReplyService) -> None:
            resp = await client.post(REPLY_URL.format(sid="sess-closing"), json={"text": "wind down"})
            assert resp.status == 200  # the dispatch itself succeeded; the delivery did not
            payload = await resp.json()
            assert payload["ok"] is False
            receipt = payload["receipt"]
            assert receipt["state"] == "failed"
            assert receipt["undelivered"] is True
            assert receipt["reason"] == "channel_rejected"

        return service, body

    _run(setup)


def test_erroring_channel_is_reported_as_failed_not_a_500() -> None:
    def setup():
        service = _service()
        service.register_session("sess-broken", FakeChannel(raises=ConnectionError("socket gone")))

        async def body(client: TestClient, svc: FleetReplyService) -> None:
            resp = await client.post(REPLY_URL.format(sid="sess-broken"), json={"text": "are you alive"})
            assert resp.status == 200
            receipt = (await resp.json())["receipt"]
            assert receipt["state"] == "failed"
            assert receipt["undelivered"] is True
            assert "channel_error" in receipt["reason"]

        return service, body

    _run(setup)


# --------------------------------------------------------------------------- #
# dashboard read surfaces
# --------------------------------------------------------------------------- #
def test_sessions_listing_rolls_up_last_receipt_for_each_row() -> None:
    def setup():
        service = _service()
        service.register_session("sess-b", FakeChannel())
        service.register_session("sess-a", FakeChannel())

        async def body(client: TestClient, svc: FleetReplyService) -> None:
            empty = await (await client.get("/api/fleet/reply/sessions")).json()
            assert [s["id"] for s in empty["sessions"]] == ["sess-a", "sess-b"]
            assert empty["count"] == 2
            assert empty["sessions"][0]["last_receipt"] is None

            await client.post(REPLY_URL.format(sid="sess-a"), json={"text": "first"})
            second = await (await client.post(REPLY_URL.format(sid="sess-a"), json={"text": "second"})).json()
            await client.post(ACK_URL.format(rid=second["receipt"]["id"]))

            listing = await (await client.get("/api/fleet/reply/sessions")).json()
            row_a = next(s for s in listing["sessions"] if s["id"] == "sess-a")
            assert row_a["reply_count"] == 2
            assert row_a["acked_count"] == 1
            assert row_a["last_receipt"]["text"] == "second"
            assert row_a["last_receipt"]["state"] == "acked"
            row_b = next(s for s in listing["sessions"] if s["id"] == "sess-b")
            assert row_b["reply_count"] == 0

        return service, body

    _run(setup)


def test_receipts_listing_is_dispatch_ordered_and_filterable() -> None:
    def setup():
        service = _service()
        service.register_session("sess-a", FakeChannel())
        service.register_session("sess-b", FakeChannel())

        async def body(client: TestClient, svc: FleetReplyService) -> None:
            for text in ("one", "two", "three"):
                await client.post(REPLY_URL.format(sid="sess-a"), json={"text": text})
            await client.post(REPLY_URL.format(sid="sess-b"), json={"text": "other"})

            everything = await (await client.get("/api/fleet/reply/receipts")).json()
            assert [r["text"] for r in everything["receipts"]] == ["one", "two", "three", "other"]
            assert everything["count"] == 4

            just_a = await (await client.get("/api/fleet/reply/receipts?session_id=sess-a")).json()
            assert [r["text"] for r in just_a["receipts"]] == ["one", "two", "three"]
            assert [r["seq"] for r in just_a["receipts"]] == [1, 2, 3]

        return service, body

    _run(setup)


def test_registering_a_session_over_http_makes_it_replyable() -> None:
    def setup():
        service = _service()

        async def body(client: TestClient, svc: FleetReplyService) -> None:
            created = await client.post("/api/fleet/reply/sessions", json={"session_id": "sess-new"})
            assert created.status == 200
            assert (await created.json())["session"]["id"] == "sess-new"

            resp = await client.post(REPLY_URL.format(sid="sess-new"), json={"text": "welcome aboard"})
            assert resp.status == 200
            # default InboxChannel accepts -> delivered acknowledgement
            assert (await resp.json())["receipt"]["state"] == "delivered"

        return service, body

    _run(setup)


# --------------------------------------------------------------------------- #
# auth guard + singleton accessor
# --------------------------------------------------------------------------- #
def test_require_api_access_guard_is_applied_to_every_route() -> None:
    seen: list[str] = []

    def guard(request) -> None:
        seen.append(request.path)
        raise web.HTTPUnauthorized(text='{"ok": false}', content_type="application/json")

    async def runner() -> None:
        service = _service()
        service.register_session("sess-alpha", FakeChannel())
        app = web.Application()
        register_fleet_reply_routes(
            app,
            None,
            require_api_access=guard,
            service_resolver=lambda: service,
        )
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            assert (await client.get("/api/fleet/reply/sessions")).status == 401
            assert (await client.post(REPLY_URL.format(sid="sess-alpha"), json={"text": "x"})).status == 401
            assert (await client.post(ACK_URL.format(rid="rcpt-1"))).status == 401
            assert (await client.get("/api/fleet/reply/receipts")).status == 401
        finally:
            await client.close()
        assert len(seen) == 4

    asyncio.run(runner())


def test_module_singleton_is_shared_and_resettable() -> None:
    reset_fleet_reply_service()
    try:
        first = get_fleet_reply_service()
        assert get_fleet_reply_service() is first
        injected = _service()
        assert set_fleet_reply_service(injected) is injected
        assert get_fleet_reply_service() is injected
        reset_fleet_reply_service()
        assert get_fleet_reply_service() is not injected
    finally:
        reset_fleet_reply_service()
