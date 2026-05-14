import argparse
import importlib

import pytest

from thomas.cli.commands.messages import p056_message_delete_command as cli_mod
from thomas.messages.p056_message_delete_command import (
    MessageDeleteError,
    MessageDeleteRequest,
    build_default_deleter,
    delete_message,
)


class _StubDeleter:
    def __init__(self, *, result=True, exc=None):
        self.calls = []
        self._result = result
        self._exc = exc

    def delete_message(self, *, channel, account, target, message_id):
        self.calls.append(
            {
                "channel": channel,
                "account": account,
                "target": target,
                "message_id": message_id,
            }
        )
        if self._exc:
            raise self._exc
        return self._result


def test_delete_message_success():
    deleter = _StubDeleter(result=True)
    req = MessageDeleteRequest(target="channel:123", message_id="456", channel="slack", account=None)
    resp = delete_message(req, deleter=deleter)

    assert resp.deleted is True
    assert resp.to_dict()["to"] == "channel:123"
    assert resp.to_dict()["messageId"] == "456"
    assert deleter.calls == [
        {"channel": "slack", "account": None, "target": "channel:123", "message_id": "456"}
    ]


def test_delete_message_dry_run_skips_backend():
    deleter = _StubDeleter(result=True)
    req = MessageDeleteRequest(target="channel:123", message_id="456", dry_run=True)
    resp = delete_message(req, deleter=deleter)

    assert resp.dry_run is True
    assert resp.deleted is False
    assert deleter.calls == []


def test_delete_message_invalid_input_is_deterministic():
    with pytest.raises(MessageDeleteError) as ei:
        delete_message(MessageDeleteRequest(target="x", message_id=""))

    err = ei.value
    assert err.code == "invalid_input"
    assert "message_id" in err.message


def test_default_deleter_missing_config_is_deterministic(monkeypatch):
    # Make backend discovery deterministic by forcing all candidate imports to fail.
    real_import = importlib.import_module

    def _always_fail(name, *a, **k):
        raise ImportError(name)

    monkeypatch.setattr(importlib, "import_module", _always_fail)
    try:
        with pytest.raises(MessageDeleteError) as ei:
            build_default_deleter()
    finally:
        monkeypatch.setattr(importlib, "import_module", real_import)

    err = ei.value
    assert err.code == "config_missing"


def test_cli_add_arguments_registers_expected_flags():
    parser = argparse.ArgumentParser()
    cli_mod.add_arguments(parser)
    opts = {o for a in parser._actions for o in a.option_strings}

    assert "--target" in opts
    assert "--to" in opts
    assert "--message-id" in opts
    assert "--dry-run" in opts
    assert "--json" in opts


def test_cli_run_success(monkeypatch):
    deleter = _StubDeleter(result=True)

    monkeypatch.setattr(
        "thomas.messages.p056_message_delete_command.build_default_deleter",
        lambda: deleter,
    )

    args = argparse.Namespace(
        channel="discord",
        account=None,
        target="channel:123",
        message_id="999",
        dry_run=False,
        json=True,
    )

    out = cli_mod.run(args)
    assert out["deleted"] is True
    assert out["messageId"] == "999"
    assert out["to"] == "channel:123"


def test_cli_run_external_failure(monkeypatch):
    deleter = _StubDeleter(exc=RuntimeError("boom"))

    monkeypatch.setattr(
        "thomas.messages.p056_message_delete_command.build_default_deleter",
        lambda: deleter,
    )

    args = argparse.Namespace(
        channel="slack",
        account=None,
        target="C123",
        message_id="456",
        dry_run=False,
        json=True,
    )

    with pytest.raises(MessageDeleteError) as ei:
        cli_mod.run(args)

    err = ei.value
    assert err.code == "external_failure"
