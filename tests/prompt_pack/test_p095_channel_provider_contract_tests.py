import json
import sys
import types

import pytest


def _install_fake_telegram_module(monkeypatch):
    """Ensure contract tests don't depend on real network or real integration."""

    fake = types.ModuleType("thomas.integrations.telegram")

    def send_message(*args, **kwargs):
        return {"ok": True}

    fake.send_message = send_message

    monkeypatch.setitem(sys.modules, "thomas.integrations.telegram", fake)


class _FakeHTTPResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_contract_tests_success(monkeypatch):
    _install_fake_telegram_module(monkeypatch)

    from thomas.marketplace.channels.p095_channel_provider_contract_tests import (
        ProviderContractTestRequest,
        run_channel_provider_contract_tests,
    )

    def fake_urlopen(req, timeout):
        assert "getMe" in getattr(req, "full_url", str(req))
        return _FakeHTTPResponse({"ok": True, "result": {"is_bot": True}})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    report = run_channel_provider_contract_tests(
        ProviderContractTestRequest(
            provider="telegram",
            config={"token": "123:ABC", "chat_id": "456"},
            run_external=True,
            timeout_seconds=1.0,
        )
    )

    assert report.provider == "telegram"
    assert report.ok is True
    assert any(c.name == "import" and c.ok for c in report.checks)
    assert any(c.name == "config" and c.ok for c in report.checks)
    assert any(c.name == "external_health" and c.ok for c in report.checks)
    assert report.errors == []


def test_contract_tests_missing_config_is_deterministic(monkeypatch):
    _install_fake_telegram_module(monkeypatch)

    from thomas.marketplace.channels.p095_channel_provider_contract_tests import (
        ERROR_MISSING_CONFIG,
        ProviderContractTestRequest,
        run_channel_provider_contract_tests,
    )

    report = run_channel_provider_contract_tests(ProviderContractTestRequest(provider="telegram", config={}))

    assert report.ok is False
    assert report.errors
    assert report.errors[0].code == ERROR_MISSING_CONFIG


def test_contract_tests_external_failure_is_deterministic(monkeypatch):
    _install_fake_telegram_module(monkeypatch)

    from thomas.marketplace.channels.p095_channel_provider_contract_tests import (
        ERROR_EXTERNAL_FAILURE,
        ProviderContractTestRequest,
        run_channel_provider_contract_tests,
    )

    def boom(*args, **kwargs):
        raise RuntimeError("network is down")

    monkeypatch.setattr("urllib.request.urlopen", boom)

    report = run_channel_provider_contract_tests(
        ProviderContractTestRequest(
            provider="telegram",
            config={"token": "123:ABC", "chat_id": "456"},
            run_external=True,
        )
    )

    assert report.ok is False
    assert any(e.code == ERROR_EXTERNAL_FAILURE for e in report.errors)


def test_cli_json_success(monkeypatch):
    _install_fake_telegram_module(monkeypatch)

    try:
        from click.testing import CliRunner
    except Exception:
        pytest.skip("click not installed")

    from thomas.cli.commands.channel_ops.p095_channel_provider_contract_tests import COMMAND

    if COMMAND is None:
        pytest.skip("click command not available")

    def fake_urlopen(req, timeout):
        return _FakeHTTPResponse({"ok": True})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    runner = CliRunner()
    result = runner.invoke(
        COMMAND,
        [
            "--provider",
            "telegram",
            "--token",
            "123:ABC",
            "--chat-id",
            "456",
            "--external",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["provider"] == "telegram"
    assert payload["ok"] is True


def test_cli_json_failure_missing_config(monkeypatch):
    _install_fake_telegram_module(monkeypatch)

    try:
        from click.testing import CliRunner
    except Exception:
        pytest.skip("click not installed")

    from thomas.cli.commands.channel_ops.p095_channel_provider_contract_tests import COMMAND

    if COMMAND is None:
        pytest.skip("click command not available")

    runner = CliRunner()
    result = runner.invoke(COMMAND, ["--provider", "telegram", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["errors"], payload
