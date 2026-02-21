from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Dict, Optional

import pytest


def _import_module(module_name: str, rel_path: str):
    """Import a module from an installed project, or load it from a repo-relative file path."""

    try:
        return importlib.import_module(module_name)
    except Exception:
        repo_root = Path(__file__).resolve().parents[2]
        path = repo_root / rel_path
        spec = importlib.util.spec_from_file_location(module_name, path)
        assert spec is not None and spec.loader is not None, f"Unable to load {module_name} from {path}"
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod


class DummyResponse:
    def __init__(self, *, status_code: int = 200, text: str = "ok", json_data: Optional[Dict[str, Any]] = None):
        self.status_code = status_code
        self.text = text
        self._json_data = json_data

    def json(self):
        if self._json_data is None:
            raise ValueError("no json")
        return self._json_data


def test_thread_reply_success_via_webhook(monkeypatch):
    impl = _import_module("thomas.messages.p059_message_thread_reply", "thomas/messages/p059_message_thread_reply.py")

    calls: Dict[str, Any] = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        calls["url"] = url
        calls["json"] = json
        calls["headers"] = headers
        calls["timeout"] = timeout
        return DummyResponse(status_code=200, text="ok")

    monkeypatch.setenv("THOMAS_SLACK_WEBHOOK_URL", "https://example.test/webhook")

    req = impl.MessageThreadReplyRequest(thread_id="123.456", text="Hello from thread!")
    res = impl.message_thread_reply(req, http_post=fake_post)

    assert res.ok is True
    assert res.provider == "slack_webhook"
    assert res.thread_id == "123.456"
    assert res.text == "Hello from thread!"

    assert calls["url"] == "https://example.test/webhook"
    assert calls["json"]["thread_ts"] == "123.456"
    assert calls["json"]["text"] == "Hello from thread!"


def test_thread_reply_external_failure_is_deterministic(monkeypatch):
    impl = _import_module("thomas.messages.p059_message_thread_reply", "thomas/messages/p059_message_thread_reply.py")

    def fake_post(url, json=None, headers=None, timeout=None):
        return DummyResponse(status_code=500, text="nope")

    monkeypatch.setenv("THOMAS_SLACK_WEBHOOK_URL", "https://example.test/webhook")

    req = impl.MessageThreadReplyRequest(thread_id="123.456", text="Hello")
    with pytest.raises(impl.MessageThreadReplyExternalError) as excinfo:
        impl.message_thread_reply(req, http_post=fake_post)

    err = excinfo.value
    assert err.code == "provider_error"
    assert "non-200" in err.message
    assert err.details.get("status_code") == 500


def test_thread_reply_missing_config(monkeypatch):
    impl = _import_module("thomas.messages.p059_message_thread_reply", "thomas/messages/p059_message_thread_reply.py")

    monkeypatch.delenv("THOMAS_SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("THOMAS_SLACK_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)

    req = impl.MessageThreadReplyRequest(thread_id="123.456", text="Hello")
    with pytest.raises(impl.MessageThreadReplyConfigError) as excinfo:
        impl.message_thread_reply(req, config={})

    err = excinfo.value
    assert err.code == "missing_config"
    assert "No messaging credentials" in err.message


def test_provider_payload_unknown_keys_is_invalid_input(monkeypatch):
    impl = _import_module("thomas.messages.p059_message_thread_reply", "thomas/messages/p059_message_thread_reply.py")

    monkeypatch.setenv("THOMAS_SLACK_WEBHOOK_URL", "https://example.test/webhook")

    req = impl.MessageThreadReplyRequest(thread_id="123.456", text="Hello", provider_payload={"not_a_real": True})
    with pytest.raises(impl.MessageThreadReplyInputError) as excinfo:
        impl.message_thread_reply(req, http_post=lambda *a, **k: DummyResponse())

    err = excinfo.value
    assert err.code == "invalid_input"
    assert "unsupported" in err.message


def test_thread_reply_success_via_slack_web_api(monkeypatch):
    impl = _import_module("thomas.messages.p059_message_thread_reply", "thomas/messages/p059_message_thread_reply.py")

    def fake_post(url, json=None, headers=None, timeout=None):
        assert url == "https://slack.com/api/chat.postMessage"
        assert headers and headers.get("Authorization", "").startswith("Bearer ")
        return DummyResponse(
            status_code=200,
            json_data={"ok": True, "channel": "C123", "ts": "999.888"},
        )

    monkeypatch.delenv("THOMAS_SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.setenv("THOMAS_SLACK_BOT_TOKEN", "xoxb-test")

    req = impl.MessageThreadReplyRequest(
        thread_id="123.456",
        text="Hello via Web API",
        channel_id="C123",
        provider="slack_web_api",
    )
    res = impl.message_thread_reply(req, http_post=fake_post)

    assert res.ok is True
    assert res.provider == "slack_web_api"
    assert res.message_id == "999.888"
    assert res.channel_id == "C123"


def test_cli_json_output_success(monkeypatch, capsys):
    # Patch requests.post at the library level since the CLI loads impl lazily.
    import requests

    def fake_post(url, json=None, headers=None, timeout=None):
        return DummyResponse(status_code=200, text="ok")

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setenv("THOMAS_SLACK_WEBHOOK_URL", "https://example.test/webhook")

    cli = _import_module(
        "thomas.cli.commands.messages.p059_message_thread_reply",
        "thomas/cli/commands/messages/p059_message_thread_reply.py",
    )

    exit_code = cli.main(["--thread-id", "123.456", "--text", "hi", "--json"])
    assert exit_code == 0

    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["result"]["thread_id"] == "123.456"
    assert payload["result"]["provider"] == "slack_webhook"
    assert payload["result"]["schema_version"] == 1


def test_cli_json_output_error(monkeypatch, capsys):
    # Ensure no config present
    monkeypatch.delenv("THOMAS_SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("THOMAS_SLACK_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)

    cli = _import_module(
        "thomas.cli.commands.messages.p059_message_thread_reply",
        "thomas/cli/commands/messages/p059_message_thread_reply.py",
    )

    exit_code = cli.main(["--thread-id", "123.456", "--text", "hi", "--json"])
    assert exit_code != 0

    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "missing_config"
