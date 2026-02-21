import json

import pytest

from thomas.nodes.p039_nodes_invoke_action import (
    InvokeActionRequest,
    MissingNodeConfig,
    RemoteFailure,
    TransportFailure,
    invoke_action,
)


class _DummyResponse:
    def __init__(self, status_code: int, json_data=None, text: str = ""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self):
        if isinstance(self._json_data, Exception):
            raise self._json_data
        return self._json_data


class _DummySession:
    def __init__(self, fn):
        self._fn = fn

    def post(self, *a, **k):
        return self._fn(*a, **k)


def test_invoke_action_success_parses_result():
    seen = {}

    def _post(url, json=None, timeout=None, headers=None):
        seen["url"] = url
        seen["json"] = json
        seen["timeout"] = timeout
        return _DummyResponse(200, {"result": {"pong": True}})

    session = _DummySession(_post)

    req = InvokeActionRequest(node="n1", action="ping", payload={"x": 1}, timeout_s=5.0)
    resp = invoke_action(req, registry={"n1": "http://node.local"}, session=session)

    assert resp.ok is True
    assert resp.node == "n1"
    assert resp.action == "ping"
    assert resp.status_code == 200
    assert resp.result == {"pong": True}
    assert seen["url"] == "http://node.local/actions/invoke"
    assert seen["json"]["action"] == "ping"
    assert seen["json"]["payload"] == {"x": 1}
    assert seen["timeout"] == 5.0


def test_invoke_action_missing_config_is_deterministic():
    req = InvokeActionRequest(node="unknown", action="ping")
    with pytest.raises(MissingNodeConfig) as exc:
        invoke_action(req, registry={})

    assert exc.value.code == "missing_config"
    assert exc.value.details.get("node") == "unknown"


def test_invoke_action_transport_failure_is_deterministic():
    import requests

    def _post(*_a, **_k):
        raise requests.exceptions.Timeout("boom")

    session = _DummySession(_post)

    req = InvokeActionRequest(node="n1", action="ping")
    with pytest.raises(TransportFailure) as exc:
        invoke_action(req, registry={"n1": "http://node.local"}, session=session)

    assert exc.value.code == "transport_failure"
    assert exc.value.details.get("error") == "Timeout"


def test_invoke_action_remote_failure_is_deterministic():
    def _post(*_a, **_k):
        return _DummyResponse(500, {"error": "boom"})

    session = _DummySession(_post)

    req = InvokeActionRequest(node="n1", action="ping")
    with pytest.raises(RemoteFailure) as exc:
        invoke_action(req, registry={"n1": "http://node.local"}, session=session)

    assert exc.value.code == "remote_failure"
    assert exc.value.details.get("status_code") == 500


def test_invoke_action_remote_ok_false_is_failure():
    def _post(*_a, **_k):
        return _DummyResponse(200, {"ok": False, "error": {"code": "bad", "message": "nope"}})

    session = _DummySession(_post)

    req = InvokeActionRequest(node="n1", action="ping")
    with pytest.raises(RemoteFailure) as exc:
        invoke_action(req, registry={"n1": "http://node.local"}, session=session)

    assert exc.value.code == "remote_failure"
    assert exc.value.details.get("status_code") == 200
    assert isinstance(exc.value.details.get("error"), dict)


def test_cli_json_success(monkeypatch, capsys):
    monkeypatch.setenv("THOMAS_NODE_REGISTRY", json.dumps({"n1": "http://node.local"}))

    from thomas.cli.commands.nodes import p039_nodes_invoke_action as cli_mod
    from thomas.nodes import p039_nodes_invoke_action as nodes_mod

    def _post(url, json=None, timeout=None, headers=None):
        return _DummyResponse(200, {"result": {"ok": True, "echo": json}})

    monkeypatch.setattr(nodes_mod.requests, "post", _post)

    rc = cli_mod.main(["--node", "n1", "--action", "ping", "--payload", "{}", "--json"])
    assert rc == 0

    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["node"] == "n1"
    assert payload["action"] == "ping"
    assert payload["result"]["ok"] is True


def test_cli_json_failure_on_bad_payload(monkeypatch, capsys):
    monkeypatch.setenv("THOMAS_NODE_REGISTRY", json.dumps({"n1": "http://node.local"}))

    from thomas.cli.commands.nodes import p039_nodes_invoke_action as cli_mod

    rc = cli_mod.main(["--node", "n1", "--action", "ping", "--payload", "not-json", "--json"])
    assert rc == 1

    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_input"
