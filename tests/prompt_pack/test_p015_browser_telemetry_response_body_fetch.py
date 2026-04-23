from __future__ import annotations

import asyncio
import base64
import json

import pytest
import typer
from typer.testing import CliRunner

from thomas.browser.p015_browser_telemetry_response_body_fetch import (
    BrowserTelemetryResponseBodyFetchError,
    BrowserTelemetryResponseBodyFetchRequest,
    BrowserTelemetryResponseBodyFetchResult,
    async_fetch_browser_telemetry_response_body,
    fetch_browser_telemetry_response_body,
)
from thomas.cli.commands.browser import p015_browser_telemetry_response_body_fetch as cli_mod


class FakeBackend:
    def __init__(self, payload):
        self._payload = payload

    def get_response_body(self, request_id: str, *, timeout_s: float | None = None):
        # Return the payload regardless of request_id for test simplicity.
        return self._payload


def test_fetch_success_text_body():
    backend = FakeBackend(
        {
            "body": '{"ok": true}',
            "base64Encoded": False,
            "contentType": "application/json",
            "url": "https://example.test/api",
            "status": 200,
        }
    )
    req = BrowserTelemetryResponseBodyFetchRequest(request_id="req-123")
    res = fetch_browser_telemetry_response_body(req, backend=backend)

    assert res.request_id == "req-123"
    assert res.body_text == '{"ok": true}'
    assert base64.b64decode(res.body_base64.encode("ascii")) == b'{"ok": true}'
    assert res.content_type == "application/json"
    assert res.url == "https://example.test/api"
    assert res.status == 200
    assert res.truncated is False
    assert res.original_base64_encoded is False


def test_fetch_success_base64_body_and_truncation():
    raw = b"\xff\xfe\xfd\x00\x01"
    backend = FakeBackend({"body": base64.b64encode(raw).decode("ascii"), "base64Encoded": True})
    req = BrowserTelemetryResponseBodyFetchRequest(request_id="abc", max_bytes=2)
    res = fetch_browser_telemetry_response_body(req, backend=backend)

    assert res.original_base64_encoded is True
    assert res.truncated is True
    assert res.original_size_bytes == len(raw)
    assert res.returned_size_bytes == 2
    assert base64.b64decode(res.body_base64.encode("ascii")) == raw[:2]
    assert res.body_text is None  # truncated binary


def test_fetch_invalid_input_is_deterministic():
    backend = FakeBackend({"body": "x", "base64Encoded": False})
    with pytest.raises(BrowserTelemetryResponseBodyFetchError) as exc:
        fetch_browser_telemetry_response_body(
            BrowserTelemetryResponseBodyFetchRequest(request_id="   "), backend=backend
        )

    assert exc.value.code == "invalid_input"
    assert "request_id" in exc.value.message


def test_fetch_external_failure_is_deterministic():
    class BoomBackend:
        def get_response_body(self, request_id: str, *, timeout_s: float | None = None):
            raise RuntimeError("boom")

    with pytest.raises(BrowserTelemetryResponseBodyFetchError) as exc:
        fetch_browser_telemetry_response_body(
            BrowserTelemetryResponseBodyFetchRequest(request_id="abc"), backend=BoomBackend()
        )

    assert exc.value.code == "external_failure"
    assert "failed" in exc.value.message.lower()


def test_fetch_async_backend_supported_in_sync_when_no_loop():
    class AsyncBackend:
        async def get_response_body(self, request_id: str, *, timeout_s: float | None = None):
            return {"body": "hello", "base64Encoded": False}

    res = fetch_browser_telemetry_response_body(
        BrowserTelemetryResponseBodyFetchRequest(request_id="abc"),
        backend=AsyncBackend(),
    )
    assert res.body_text == "hello"


def test_fetch_sync_rejects_async_inside_event_loop():
    class AsyncBackend:
        async def get_response_body(self, request_id: str, *, timeout_s: float | None = None):
            return {"body": "hello", "base64Encoded": False}

    async def _inner():
        with pytest.raises(BrowserTelemetryResponseBodyFetchError) as exc:
            fetch_browser_telemetry_response_body(
                BrowserTelemetryResponseBodyFetchRequest(request_id="abc"),
                backend=AsyncBackend(),
            )
        assert exc.value.code == "invalid_context"

    asyncio.run(_inner())


def test_async_api_works_inside_event_loop():
    class AsyncBackend:
        async def get_response_body(self, request_id: str, *, timeout_s: float | None = None):
            return {"body": "hello", "base64Encoded": False}

    async def _inner():
        res = await async_fetch_browser_telemetry_response_body(
            BrowserTelemetryResponseBodyFetchRequest(request_id="abc"),
            backend=AsyncBackend(),
        )
        assert res.body_text == "hello"

    asyncio.run(_inner())


def test_cli_json_success(monkeypatch):
    app = typer.Typer()

    @app.command("dummy")
    def _dummy() -> None:
        return

    cli_mod.register(app)

    fake_result = BrowserTelemetryResponseBodyFetchResult(
        request_id="abc",
        body_base64=base64.b64encode(b"hi").decode("ascii"),
        body_text="hi",
        content_type="text/plain",
        url="https://example.test",
        status=200,
        original_size_bytes=2,
        returned_size_bytes=2,
        truncated=False,
        original_base64_encoded=False,
    )

    def _fake_fetch(_req):
        return fake_result

    monkeypatch.setattr(cli_mod, "fetch_browser_telemetry_response_body", _fake_fetch)

    runner = CliRunner()
    result = runner.invoke(app, ["telemetry-response-body-fetch", "abc", "--json"])
    assert result.exit_code == 0

    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["result"]["request_id"] == "abc"
    assert payload["result"]["body_text"] == "hi"


def test_cli_human_success(monkeypatch):
    app = typer.Typer()

    @app.command("dummy")
    def _dummy() -> None:
        return

    cli_mod.register(app)

    def _fake_fetch(_req):
        return BrowserTelemetryResponseBodyFetchResult(
            request_id="abc",
            body_base64=base64.b64encode(b"hi").decode("ascii"),
            body_text="hi",
            content_type=None,
            url=None,
            status=None,
            original_size_bytes=2,
            returned_size_bytes=2,
            truncated=False,
            original_base64_encoded=False,
        )

    monkeypatch.setattr(cli_mod, "fetch_browser_telemetry_response_body", _fake_fetch)

    runner = CliRunner()
    result = runner.invoke(app, ["telemetry-response-body-fetch", "abc"])
    assert result.exit_code == 0
    assert result.stdout.strip() == "hi"


def test_cli_json_error(monkeypatch):
    app = typer.Typer()

    @app.command("dummy")
    def _dummy() -> None:
        return

    cli_mod.register(app)

    def _fake_fetch(_req):
        raise BrowserTelemetryResponseBodyFetchError(code="missing_config", message="nope")

    monkeypatch.setattr(cli_mod, "fetch_browser_telemetry_response_body", _fake_fetch)

    runner = CliRunner()
    result = runner.invoke(app, ["telemetry-response-body-fetch", "abc", "--json"])
    assert result.exit_code == 1

    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "missing_config"
