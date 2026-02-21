import json
import io
from types import SimpleNamespace
from unittest import mock

import pytest
from urllib import error as urlerror

from thomas.channels.p090_channel_webhook_bridge_adapter import (
    WebhookBridgeAdapterError,
    WebhookBridgeSendRequest,
    send_via_webhook_bridge,
    webhook_bridge_payload_schema,
)


class _FakeResp:
    def __init__(self, status: int = 200, body: bytes = b"ok"):
        self.status = status
        self._body = body

    def getcode(self):
        return self.status

    def read(self, n=2048):
        return self._body[:n]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_payload_schema_has_required_text():
    schema = webhook_bridge_payload_schema()
    assert schema["type"] == "object"
    assert "text" in schema["properties"]
    assert "text" in schema["required"]


def test_send_success_posts_json_payload():
    captured = {}

    def fake_urlopen(req, timeout=None, context=None):
        captured["method"] = req.get_method()
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        body = req.data or b""
        captured["body"] = body
        return _FakeResp(status=204, body=b"")

    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
        req = WebhookBridgeSendRequest(
            url="https://example.com/webhook",
            payload={"text": "hello", "metadata": {"k": "v"}},
            method="POST",
            headers={"X-Test": "1"},
            timeout_s=5.0,
            verify_tls=True,
        )
        result = send_via_webhook_bridge(req)

    assert result.ok is True
    assert result.status_code == 204
    assert captured["method"] == "POST"
    assert captured["url"] == "https://example.com/webhook"
    headers = {k.lower(): v for k, v in captured["headers"].items()}
    assert headers.get("content-type") == "application/json"
    assert headers.get("x-test") == "1"
    assert json.loads(captured["body"].decode("utf-8"))["text"] == "hello"


@pytest.mark.parametrize(
    "bad_url,code",
    [
        ("", "missing_config"),
        ("   ", "missing_config"),
        ("ftp://example.com/x", "invalid_url"),
        ("not-a-url", "invalid_url"),
    ],
)
def test_send_rejects_bad_url(bad_url, code):
    req = WebhookBridgeSendRequest(url=bad_url, payload={"text": "hi"})
    with pytest.raises(WebhookBridgeAdapterError) as ei:
        send_via_webhook_bridge(req)
    assert ei.value.code == code


def test_send_request_failure_is_deterministic():
    with mock.patch("urllib.request.urlopen", side_effect=urlerror.URLError("boom")):
        req = WebhookBridgeSendRequest(url="https://example.com/webhook", payload={"text": "hi"})
        with pytest.raises(WebhookBridgeAdapterError) as ei:
            send_via_webhook_bridge(req)
    assert ei.value.code == "request_failed"
    assert "boom" in str(ei.value.details.get("error", ""))


def test_send_non_2xx_is_deterministic():
    http_err = urlerror.HTTPError(
        url="https://example.com/webhook",
        code=500,
        msg="nope",
        hdrs=None,
        fp=io.BytesIO(b"nope"),
    )
    with mock.patch("urllib.request.urlopen", side_effect=http_err):
        req = WebhookBridgeSendRequest(url="https://example.com/webhook", payload={"text": "hi"})
        with pytest.raises(WebhookBridgeAdapterError) as ei:
            send_via_webhook_bridge(req)
    assert ei.value.code == "non_success_status"
    assert ei.value.details["status_code"] == 500


def test_cli_run_send_json_success(capsys):
    from thomas.cli.commands.channel_ops import p090_channel_webhook_bridge_adapter as cli_mod

    fake_result = SimpleNamespace(
        to_dict=lambda: {
            "ok": True,
            "status_code": 200,
            "response_text": "ok",
            "request_url": "https://example.com/webhook",
            "method": "POST",
            "error": None,
        }
    )

    with mock.patch.object(cli_mod, "send_via_webhook_bridge", return_value=fake_result):
        code = cli_mod._run_send(
            url="https://example.com/webhook",
            text="hello",
            payload_json=None,
            headers=[],
            method="POST",
            timeout_s=10.0,
            verify_tls=True,
            json_mode=True,
        )
    out = capsys.readouterr().out.strip()
    assert code == 0
    data = json.loads(out)
    assert data["ok"] is True
    assert data["status_code"] == 200


def test_cli_run_send_error_outputs_json(capsys):
    from thomas.cli.commands.channel_ops import p090_channel_webhook_bridge_adapter as cli_mod
    from thomas.channels.p090_channel_webhook_bridge_adapter import WebhookBridgeAdapterError

    with mock.patch.object(cli_mod, "send_via_webhook_bridge", side_effect=WebhookBridgeAdapterError(code="missing_config", message="no url")):
        code = cli_mod._run_send(
            url=None,
            text="hello",
            payload_json=None,
            headers=[],
            method="POST",
            timeout_s=10.0,
            verify_tls=True,
            json_mode=False,
        )
    out = capsys.readouterr().out.strip()
    assert code == 1
    data = json.loads(out)
    assert data["ok"] is False
    assert data["error"]["code"] == "missing_config"


def test_cli_schema_outputs_json(capsys):
    from thomas.cli.commands.channel_ops import p090_channel_webhook_bridge_adapter as cli_mod

    code = cli_mod._run_schema(json_mode=False)
    out = capsys.readouterr().out.strip()
    assert code == 0
    schema = json.loads(out)
    assert schema["type"] == "object"
