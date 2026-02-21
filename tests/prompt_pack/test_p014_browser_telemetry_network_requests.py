import argparse
import json
from contextlib import contextmanager

import pytest


def test_p014_capture_network_requests_invalid_input():
    from thomas.browser.p014_browser_telemetry_network_requests import (
        BrowserNetworkRequestsInput,
        BrowserTelemetryInputError,
        capture_network_requests,
    )

    with pytest.raises(BrowserTelemetryInputError) as excinfo:
        capture_network_requests(BrowserNetworkRequestsInput(duration_seconds=0))

    assert excinfo.value.code == "invalid_input"


def test_p014_capture_network_requests_collects_and_correlates(monkeypatch):
    import thomas.browser.p014_browser_telemetry_network_requests as mod

    class FakeRequest:
        def __init__(self, guid):
            self._guid = guid
            self.method = "GET"
            self.url = "https://example.test/api"
            self.resource_type = "xhr"

    class FakeResponse:
        def __init__(self, req_guid):
            # Return a *different* request wrapper with the same guid to ensure
            # correlation doesn't rely on Python object identity.
            self._req = FakeRequest(req_guid)
            self.status = 200

        def request(self):
            return self._req

    class FakePage:
        def __init__(self, clock):
            self._handlers = {}
            self._clock = clock
            self._fired = False
            self._req = FakeRequest("req-1")
            self._resp = FakeResponse("req-1")

        def on(self, event, cb):
            self._handlers.setdefault(event, []).append(cb)

        def wait_for_timeout(self, ms):
            # Fire exactly one request+response and advance fake time.
            if not self._fired:
                self._fired = True
                for cb in self._handlers.get("request", []):
                    cb(self._req)
                self._clock["t"] += ms / 1000.0
                for cb in self._handlers.get("response", []):
                    cb(self._resp)
            else:
                self._clock["t"] += ms / 1000.0

    class FakeContext:
        def __init__(self, page):
            self.pages = [page]
            self._handlers = {}

        def on(self, event, cb):
            self._handlers.setdefault(event, []).append(cb)

    class FakeBrowser:
        def __init__(self, ctx):
            self.contexts = [ctx]

    clock = {"t": 0.0}
    page = FakePage(clock)
    ctx = FakeContext(page)
    browser = FakeBrowser(ctx)

    @contextmanager
    def fake_connect(_cdp_url):
        yield browser

    monkeypatch.setattr(mod, "_connect_over_cdp", fake_connect)
    monkeypatch.setattr(mod.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(mod.time, "time", lambda: 123456.789)

    out = mod.capture_network_requests(
        mod.BrowserNetworkRequestsInput(
            cdp_url="ws://fake",
            duration_seconds=0.2,
            poll_interval_seconds=0.1,
            max_entries=10,
        )
    )

    assert out.cdp_url == "ws://fake"
    assert out.truncated is False
    assert len(out.requests) == 1
    r = out.requests[0]
    assert r.method == "GET"
    assert r.url == "https://example.test/api"
    assert r.response_status == 200


def test_p014_cli_json_success(monkeypatch, capsys):
    import thomas.cli.commands.browser.p014_browser_telemetry_network_requests as cli
    import thomas.browser.p014_browser_telemetry_network_requests as core

    def fake_capture(_req, *, on_event=None):
        return core.BrowserNetworkRequestsOutput(
            requests=[
                core.BrowserNetworkRequest(
                    id="1",
                    timestamp_ms=1,
                    method="GET",
                    url="https://example.test/api",
                    response_status=200,
                )
            ],
            truncated=False,
            duration_seconds=0.01,
            cdp_url="ws://fake",
        )

    monkeypatch.setattr(core, "capture_network_requests", fake_capture)

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    cli.register(sub)

    args = parser.parse_args(["p014-browser-telemetry-network-requests", "--json", "--cdp-url", "ws://fake"])
    rc = args.func(args)

    assert rc == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["requests"][0]["response_status"] == 200


def test_p014_cli_json_failure(monkeypatch, capsys):
    import thomas.cli.commands.browser.p014_browser_telemetry_network_requests as cli
    import thomas.browser.p014_browser_telemetry_network_requests as core

    def fake_capture(_req, *, on_event=None):
        raise core.BrowserTelemetryConfigError(code="browser_endpoint_missing", message="no endpoint")

    monkeypatch.setattr(core, "capture_network_requests", fake_capture)

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    cli.register(sub)

    args = parser.parse_args(["p014-browser-telemetry-network-requests", "--json"])
    rc = args.func(args)

    assert rc != 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["error"]["code"] == "browser_endpoint_missing"


def test_p014_cli_json_schema(capsys):
    import thomas.cli.commands.browser.p014_browser_telemetry_network_requests as cli

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    cli.register(sub)

    args = parser.parse_args(["p014-browser-telemetry-network-requests", "--json-schema"])
    rc = args.func(args)

    assert rc == 0
    schema = json.loads(capsys.readouterr().out.strip())
    assert schema["title"] == "BrowserNetworkRequestsOutput"
