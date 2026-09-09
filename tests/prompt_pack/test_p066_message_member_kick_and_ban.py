import json

import pytest
from typer.testing import CliRunner

from thomas.messages.p066_message_member_kick_and_ban import (
    ExternalServiceError,
    InvalidInputError,
    MemberModerationRequest,
    MissingConfigError,
    execute,
    parse_request,
    run,
)


class _FakeResp:
    def __init__(self, status_code: int = 200, json_body=None, text: str = ""):
        self.status_code = status_code
        self._json_body = json_body
        self.text = text

    def json(self):
        if isinstance(self._json_body, Exception):
            raise self._json_body
        return self._json_body


class _FakeSession:
    def __init__(self, resp: _FakeResp):
        self._resp = resp
        self.last_call = None

    def post(self, url, json=None, timeout=None, headers=None):
        self.last_call = {"url": url, "json": json, "timeout": timeout, "headers": headers}
        return self._resp


def test_parse_request_happy_path():
    req = parse_request({"action": "kick", "channel_id": "C1", "member_id": "U1", "reason": "spam"})
    assert req.action == "kick"
    assert req.channel_id == "C1"
    assert req.member_id == "U1"
    assert req.reason == "spam"


def test_parse_request_accepts_action_alias_remove():
    req = parse_request({"action": "remove", "channel_id": "C1", "member_id": "U1"})
    assert req.action == "kick"


def test_parse_request_rejects_missing_member_id():
    with pytest.raises(InvalidInputError) as exc:
        parse_request({"action": "ban", "channel_id": "C1"})
    assert exc.value.code == "invalid_input"


def test_execute_requires_webhook_url():
    req = MemberModerationRequest(action="kick", channel_id="C1", member_id="U1")
    with pytest.raises(MissingConfigError):
        execute(req, webhook_url="")


def test_execute_external_failure_non_2xx():
    session = _FakeSession(_FakeResp(status_code=500, text="nope"))
    req = MemberModerationRequest(action="ban", channel_id="C1", member_id="U1")
    with pytest.raises(ExternalServiceError) as exc:
        execute(req, webhook_url="https://example.test/hook", timeout_s=1, session=session)
    assert exc.value.code == "external_failure"
    assert exc.value.details.get("status_code") == 500


def test_execute_non_json_response_ok():
    session = _FakeSession(_FakeResp(status_code=200, json_body=ValueError("no json"), text="OK"))
    req = MemberModerationRequest(action="kick", channel_id="C1", member_id="U1")
    out = execute(req, webhook_url="https://example.test/hook", timeout_s=1, session=session)
    assert out.message
    assert out.provider_response is not None
    assert "raw" in out.provider_response


def test_run_success_json_dict():
    session = _FakeSession(_FakeResp(status_code=200, json_body={"message": "ok", "provider": "test"}))
    out = run(
        {"action": "kick", "channel_id": "C1", "member_id": "U1", "webhook_url": "https://example.test/hook"},
        session=session,
    )
    assert out["ok"] is True
    assert out["action"] == "kick"
    assert out["provider_response"]["provider"] == "test"


def test_cli_json_success(monkeypatch):
    import thomas.messages.p066_message_member_kick_and_ban as mod
    from thomas.cli.commands.messages import p066_message_member_kick_and_ban as cli

    def fake_post(url, json=None, timeout=None, headers=None):
        return _FakeResp(status_code=200, json_body={"message": "ok"})

    monkeypatch.setattr(mod.requests, "post", fake_post)

    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        [
            "moderate-member",
            "--action",
            "kick",
            "--channel-id",
            "C1",
            "--member-id",
            "U1",
            "--webhook-url",
            "https://example.test/hook",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["action"] == "kick"


def test_cli_json_failure_missing_webhook():
    from thomas.cli.commands.messages import p066_message_member_kick_and_ban as cli

    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        [
            "moderate-member",
            "--action",
            "kick",
            "--channel-id",
            "C1",
            "--member-id",
            "U1",
            "--json",
        ],
    )
    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "missing_config"
