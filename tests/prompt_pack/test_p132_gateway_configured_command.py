import json
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from thomas.server.routes.gateway.p132_gateway_configured_command import (
    REASON_MISSING_CONFIG,
    REASON_MISSING_GATEWAY_MODE,
    evaluate_gateway_configured,
    gateway_configured,
)
from thomas.cli.commands.gateway.p132_gateway_configured_command import main as cli_main


def _decode_json_response(resp: web.Response) -> dict:
    assert resp.content_type == "application/json"
    body = resp.body or b""
    return json.loads(body.decode("utf-8", errors="replace"))


def _run_async(coro):
    import asyncio

    return asyncio.run(coro)


def test_evaluate_gateway_configured_true_from_app_config() -> None:
    app_like = {"config": {"gateway": {"mode": "local"}}}
    status = evaluate_gateway_configured(app_like)
    assert status.configured is True
    assert status.gateway_mode == "local"
    assert status.reason is None


def test_evaluate_gateway_configured_false_when_no_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Prevent accidental discovery of real user config on dev machines/CI.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("THOMAS_CONFIG_PATH", raising=False)
    monkeypatch.delenv("THOMAS_SETTINGS_PATH", raising=False)
    monkeypatch.delenv("THOMAS_CONFIG_FILE", raising=False)

    status = evaluate_gateway_configured({})
    assert status.configured is False
    assert status.reason == REASON_MISSING_CONFIG


def test_evaluate_gateway_configured_false_when_gateway_mode_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg_path = tmp_path / "thomas.json"
    cfg_path.write_text(json.dumps({"gateway": {}}), encoding="utf-8")
    monkeypatch.setenv("THOMAS_CONFIG_PATH", str(cfg_path))

    status = evaluate_gateway_configured({})
    assert status.configured is False
    assert status.reason == REASON_MISSING_GATEWAY_MODE


def test_route_returns_machine_readable_json() -> None:
    app = web.Application()
    app["config"] = {"gateway": {"mode": "local"}}
    req = make_mocked_request("GET", "/configured", app=app)
    resp = _run_async(gateway_configured(req))
    payload = _decode_json_response(resp)
    assert payload["configured"] is True
    assert payload["gateway_mode"] == "local"
    assert isinstance(payload["missing"], list)


def test_cli_json_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg_path = tmp_path / "thomas.json"
    cfg_path.write_text(json.dumps({"gateway": {"mode": "local"}}), encoding="utf-8")
    monkeypatch.setenv("THOMAS_CONFIG_PATH", str(cfg_path))

    code = cli_main(["--json"])
    captured = capsys.readouterr()
    assert code == 0
    data = json.loads(captured.out)
    assert data["configured"] is True


def test_cli_external_failure_is_deterministic(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    import urllib.error
    import urllib.request

    def boom(*args, **kwargs):
        raise urllib.error.URLError("boom")

    monkeypatch.setattr(urllib.request, "urlopen", boom)

    code = cli_main(["--json", "--url", "http://127.0.0.1:1"])
    captured = capsys.readouterr()
    assert code == 3
    data = json.loads(captured.out)
    assert data["configured"] is False
    assert data["reason"] in {"external_failure", "invalid_input"}
