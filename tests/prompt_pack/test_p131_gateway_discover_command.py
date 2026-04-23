import json

import pytest

from thomas.server.routes.gateway import p131_gateway_discover_command as mod


def _json_from_response(resp) -> dict:
    # aiohttp.web.Response stores bytes in .body
    raw = resp.body
    if isinstance(raw, (bytes, bytearray)):
        return json.loads(raw.decode("utf-8"))
    # Fallback; should not happen for json_response
    return json.loads(getattr(resp, "text", "") or "")


def test_discover_gateways_success_monkeypatched(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_mdns(_service_type: str, _domain: str, _timeout_ms: int):
        return [
            mod.GatewayBeacon(
                instance_name="Thomas Gateway._thomas-gw._tcp.local",
                host="gw.local",
                port=18789,
                addresses=["192.168.1.10"],
                ws_url="ws://gw.local:18789",
                txt={"role": "gateway"},
            )
        ]

    monkeypatch.setattr(mod, "_discover_via_mdns", _fake_mdns)

    result = mod.discover_gateways(
        mod.GatewayDiscoverRequest(timeout_ms=500, domain="local.", service_type="_thomas-gw._tcp")
    )

    assert result.service_type == "_thomas-gw._tcp"
    assert result.domain == "local."
    assert result.timeout_ms == 500
    assert result.elapsed_ms >= 0
    assert len(result.beacons) == 1
    assert result.beacons[0].ws_url == "ws://gw.local:18789"


def test_discover_gateways_invalid_timeout() -> None:
    with pytest.raises(mod.GatewayDiscoverInvalidInputError) as excinfo:
        mod.discover_gateways(mod.GatewayDiscoverRequest(timeout_ms=0))

    assert excinfo.value.code == "invalid_input"


def test_discover_gateways_external_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_args, **_kwargs):
        raise OSError(111, "nope")

    monkeypatch.setattr(mod, "_discover_via_mdns", _boom)

    with pytest.raises(mod.GatewayDiscoverExternalFailureError) as excinfo:
        mod.discover_gateways(mod.GatewayDiscoverRequest(timeout_ms=10))

    assert excinfo.value.code == "external_failure"


@pytest.mark.asyncio
async def test_route_invalid_timeout_returns_json_error() -> None:
    from aiohttp.test_utils import make_mocked_request

    req = make_mocked_request("GET", "/gateway/discover?timeout_ms=not_an_int")
    resp = await mod.handle_gateway_discover(req)

    assert resp.status == 400
    payload = _json_from_response(resp)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_input"


@pytest.mark.asyncio
async def test_route_schema_returns_json_schema() -> None:
    from aiohttp.test_utils import make_mocked_request

    req = make_mocked_request("GET", "/gateway/discover?schema=1")
    resp = await mod.handle_gateway_discover(req)

    assert resp.status == 200
    payload = _json_from_response(resp)
    assert payload["ok"] is True
    assert payload["schema"]["route"]["path"] == "/gateway/discover"


@pytest.mark.asyncio
async def test_route_success_returns_json_result(monkeypatch: pytest.MonkeyPatch) -> None:
    from aiohttp.test_utils import make_mocked_request

    expected = mod.GatewayDiscoverResult(
        service_type="_thomas-gw._tcp",
        domain="local.",
        timeout_ms=10,
        elapsed_ms=1,
        beacons=[
            mod.GatewayBeacon(
                instance_name="Thomas Gateway._thomas-gw._tcp.local",
                host="gw.local",
                port=18789,
                addresses=["192.168.1.10"],
                ws_url="ws://gw.local:18789",
                txt={"role": "gateway"},
            )
        ],
    )

    monkeypatch.setattr(mod, "discover_gateways", lambda _req: expected)

    req = make_mocked_request("GET", "/gateway/discover?timeout_ms=10")
    resp = await mod.handle_gateway_discover(req)

    assert resp.status == 200
    payload = _json_from_response(resp)
    assert payload["ok"] is True
    assert payload["result"]["service_type"] == "_thomas-gw._tcp"
    assert payload["result"]["beacons"][0]["ws_url"] == "ws://gw.local:18789"
