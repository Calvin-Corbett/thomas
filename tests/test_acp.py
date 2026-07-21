"""CAP-033 acceptance: native ACP discovery, invocation, cancellation, structured exchange.

Every test is hermetic (in-process, no network, no clock, no RNG) and drives the
public surface of :mod:`thomas.agent.acp`.
"""

import pytest

from thomas.agent.acp import (
    ACPBroker,
    AgentCard,
    AgentRegistry,
    Cancelled,
    CancelToken,
    EnvelopeError,
    Invocation,
    LocalTransport,
    Request,
    Result,
    Status,
    parse_request,
    parse_result,
)

# ---------------------------------------------------------------------------
# Handlers used across tests (generators = cooperative cancellation points).
# ---------------------------------------------------------------------------


def _summing_handler(request, cancel):
    """Sum 0..steps-1, yielding a cancellation checkpoint after each add."""
    steps = request.payload["steps"]
    acc = 0
    for i in range(steps):
        if cancel.cancelled:
            cancel.mark_observed()
            return  # -> cancelled, no payload
        acc += i
        yield
    return {"sum": acc}


def _echo_handler(request, cancel):
    """Non-generator handler: returns immediately (no cancellation points)."""
    return {"echo": request.payload.get("msg", "")}


def _make_broker(handler=_summing_handler, capability="math.sum"):
    broker = ACPBroker()
    broker.advertise("agent.calc", [capability], handler=handler, name="Calc")
    return broker


# ---------------------------------------------------------------------------
# DISCOVERY
# ---------------------------------------------------------------------------


def test_discovery_finds_agent_by_capability():
    reg = AgentRegistry()
    reg.register(AgentCard("agent.calc", frozenset({"math.sum", "math.mul"})))
    reg.register(AgentCard("agent.text", frozenset({"text.upper"})))

    found = reg.discover("math.sum")
    assert [c.agent_id for c in found] == ["agent.calc"]
    assert found[0].supports("math.sum")


def test_discovery_misses_unknown_capability():
    reg = AgentRegistry()
    reg.register(AgentCard("agent.calc", frozenset({"math.sum"})))

    assert reg.discover("does.not.exist") == ()
    assert reg.discover("") == ()


def test_discovery_orders_deterministically_by_agent_id():
    reg = AgentRegistry()
    for aid in ("agent.z", "agent.a", "agent.m"):
        reg.register(AgentCard(aid, frozenset({"cap.x"})))
    found = reg.discover("cap.x")
    assert [c.agent_id for c in found] == ["agent.a", "agent.m", "agent.z"]


def test_broker_discover_delegates_to_registry():
    broker = _make_broker()
    assert [c.agent_id for c in broker.discover("math.sum")] == ["agent.calc"]
    assert broker.discover("unknown") == ()


# ---------------------------------------------------------------------------
# INVOCATION -- structured round trip
# ---------------------------------------------------------------------------


def test_invocation_round_trips_structured_request_to_result():
    broker = _make_broker()
    result = broker.invoke("math.sum", {"steps": 4})
    assert isinstance(result, Result)
    assert result.status is Status.OK
    assert result.ok
    assert dict(result.result) == {"sum": 0 + 1 + 2 + 3}
    assert result.error is None


def test_invocation_non_generator_handler_round_trips():
    broker = _make_broker(handler=_echo_handler, capability="text.echo")
    result = broker.invoke("text.echo", {"msg": "hi"})
    assert result.status is Status.OK
    assert dict(result.result) == {"echo": "hi"}


def test_invocation_request_ids_are_deterministic_counter():
    broker = _make_broker()
    r1 = broker.new_request("math.sum", {"steps": 1})
    r2 = broker.new_request("math.sum", {"steps": 1})
    assert (r1.id, r2.id) == ("req-1", "req-2")


def test_invocation_unknown_capability_returns_error_status():
    broker = _make_broker()
    result = broker.invoke("nope.missing", {"steps": 1})
    assert result.status is Status.ERROR
    assert result.error
    assert "nope.missing" in result.error


def test_invocation_targets_specific_agent():
    broker = ACPBroker()
    broker.advertise("agent.a", ["cap"], handler=lambda req, c: {"who": "a"})
    broker.advertise("agent.b", ["cap"], handler=lambda req, c: {"who": "b"})
    result = broker.invoke("cap", {}, agent_id="agent.b")
    assert dict(result.result) == {"who": "b"}


def test_invocation_handler_error_becomes_error_result():
    def boom(request, cancel):
        raise KeyError("missing-field")

    broker = ACPBroker()
    broker.advertise("agent.x", ["cap"], handler=boom)
    result = broker.invoke("cap", {})
    assert result.status is Status.ERROR
    assert "missing-field" in result.error


# ---------------------------------------------------------------------------
# CANCELLATION
# ---------------------------------------------------------------------------


def test_cancelled_invocation_returns_cancelled_and_callee_observed():
    broker = _make_broker()
    request = broker.new_request("math.sum", {"steps": 5})
    inv = broker.begin(request)

    assert isinstance(inv, Invocation)
    # Advance one cooperative checkpoint, then cancel mid-flight.
    assert inv.step() is True
    assert not inv.finished
    inv.cancel()
    # Next resume: the callee observes the cancel at its checkpoint and stops.
    inv.step()

    while not inv.finished:
        inv.step()

    result = inv.result
    assert result.status is Status.CANCELLED
    assert result.cancelled
    assert not result.result  # cancelled results carry no payload
    # The invoked side actually saw and acknowledged the cancel signal.
    assert inv.cancel_token.observed is True


def test_cancel_before_first_step_is_observed():
    broker = _make_broker()
    inv = broker.begin(broker.new_request("math.sum", {"steps": 3}))
    inv.cancel()
    result = inv.run()
    assert result.status is Status.CANCELLED
    assert inv.cancel_token.observed is True


def test_handler_may_abort_via_raise_if_cancelled():
    def guarded(request, cancel):
        cancel.raise_if_cancelled()
        yield
        cancel.raise_if_cancelled()
        return {"done": True}

    broker = ACPBroker()
    broker.advertise("agent.g", ["cap"], handler=guarded)
    inv = broker.begin(broker.new_request("cap", {}))
    inv.step()
    inv.cancel()
    result = inv.run()
    assert result.status is Status.CANCELLED
    assert inv.cancel_token.observed is True


def test_uncancelled_invocation_completes_normally():
    broker = _make_broker()
    inv = broker.begin(broker.new_request("math.sum", {"steps": 3}))
    result = inv.run()
    assert result.status is Status.OK
    assert dict(result.result) == {"sum": 3}
    assert inv.cancel_token.observed is False


# ---------------------------------------------------------------------------
# STRUCTURED RESULT EXCHANGE -- validation + serialization
# ---------------------------------------------------------------------------


def test_request_envelope_serialization_round_trip():
    req = Request(id="r1", capability="cap.x", payload={"a": 1})
    restored = parse_request(req.to_dict())
    assert restored.id == "r1"
    assert restored.capability == "cap.x"
    assert dict(restored.payload) == {"a": 1}


def test_result_envelope_serialization_round_trip():
    res = Result(id="r1", capability="cap.x", status=Status.OK, result={"v": 2})
    restored = parse_result(res.to_dict())
    assert restored.status is Status.OK
    assert dict(restored.result) == {"v": 2}


def test_malformed_request_missing_capability_rejected():
    with pytest.raises(EnvelopeError):
        parse_request({"id": "r1", "payload": {}})


def test_malformed_request_empty_id_rejected():
    with pytest.raises(EnvelopeError):
        Request(id="", capability="cap", payload={})


def test_malformed_request_non_mapping_payload_rejected():
    with pytest.raises(EnvelopeError):
        Request(id="r1", capability="cap", payload=[1, 2, 3])


def test_malformed_result_ok_with_error_rejected():
    with pytest.raises(EnvelopeError):
        Result(id="r1", capability="cap", status=Status.OK, error="should not be here")


def test_malformed_result_error_without_message_rejected():
    with pytest.raises(EnvelopeError):
        Result(id="r1", capability="cap", status=Status.ERROR, error="")


def test_malformed_result_unknown_status_rejected():
    with pytest.raises(EnvelopeError):
        parse_result({"id": "r1", "capability": "cap", "status": "banana"})


def test_broker_submit_rejects_malformed_envelope_gracefully():
    broker = _make_broker()
    result = broker.submit({"id": "bad", "payload": {}})  # no capability
    assert result.status is Status.REJECTED
    assert result.error
    assert result.id == "bad"


def test_broker_submit_dispatches_valid_envelope():
    broker = _make_broker()
    raw = {"kind": "request", "id": "r9", "capability": "math.sum", "payload": {"steps": 3}}
    result = broker.submit(raw)
    assert result.status is Status.OK
    assert dict(result.result) == {"sum": 3}


def test_agent_card_serialization_is_sorted_and_stable():
    card = AgentCard("agent.calc", frozenset({"b.cap", "a.cap"}), name="Calc", meta={"tier": 1})
    data = card.to_dict()
    assert data["capabilities"] == ["a.cap", "b.cap"]  # sorted -> deterministic
    assert AgentCard.from_dict(data).capabilities == frozenset({"a.cap", "b.cap"})


# ---------------------------------------------------------------------------
# DETERMINISM
# ---------------------------------------------------------------------------


def test_full_round_trip_is_deterministic_across_runs():
    def run_once():
        broker = ACPBroker()
        broker.advertise("agent.calc", ["math.sum"], handler=_summing_handler)
        req = broker.new_request("math.sum", {"steps": 6})
        return req.to_dict(), broker.begin(req).run().to_dict()

    first = run_once()
    second = run_once()
    assert first == second
    # And the concrete expected shape:
    assert first[0]["id"] == "req-1"
    assert first[1] == {
        "kind": "result",
        "id": "req-1",
        "capability": "math.sum",
        "status": "ok",
        "result": {"sum": 0 + 1 + 2 + 3 + 4 + 5},
        "error": None,
    }


def test_cancellation_is_deterministic():
    def run_once():
        broker = _make_broker()
        inv = broker.begin(broker.new_request("math.sum", {"steps": 5}))
        inv.step()
        inv.cancel()
        return inv.run().to_dict(), inv.cancel_token.observed

    assert run_once() == run_once()


def test_injected_transport_is_used():
    # Prove the transport is injectable (hermetic; no default routing).
    class StubTransport:
        def run(self, request, cancel):
            yield  # one checkpoint
            return Result(
                id=request.id,
                capability=request.capability,
                status=Status.OK,
                result={"stub": True},
            )

    broker = ACPBroker(transport=StubTransport())
    result = broker.invoke("anything", {})
    assert dict(result.result) == {"stub": True}


def test_local_transport_directly_drivable():
    reg = AgentRegistry()
    reg.register(AgentCard("agent.calc", frozenset({"math.sum"})), _summing_handler)
    transport = LocalTransport(reg)
    cancel = CancelToken()
    driver = transport.run(Request(id="r1", capability="math.sum", payload={"steps": 2}), cancel)
    # Exhaust the generator manually.
    result = None
    try:
        while True:
            next(driver)
    except StopIteration as stop:
        result = stop.value
    assert result.status is Status.OK
    assert dict(result.result) == {"sum": 1}


def test_cancelled_exception_is_acp_error():
    assert issubclass(Cancelled, Exception)
    tok = CancelToken()
    tok.cancel()
    with pytest.raises(Cancelled):
        tok.raise_if_cancelled()
    assert tok.observed is True
