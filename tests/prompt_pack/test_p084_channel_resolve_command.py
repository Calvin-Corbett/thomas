import io
import json
import sys
import types
import importlib.util
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_module(module_name: str, rel_path: str):
    path = PROJECT_ROOT / rel_path
    assert path.exists(), f"Expected file to exist: {path}"
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def core():
    return _load_module(
        "thomas.channels.p084_channel_resolve_command",
        "thomas/channels/p084_channel_resolve_command.py",
    )


class _FakeTelegramResolver:
    def __init__(self, chat):
        self._chat = chat
        self.calls = []

    def get_chat(self, reference: str):
        self.calls.append(reference)
        return self._chat


def _ensure_cli_loaded(core):
    # Create a minimal module hierarchy so the CLI module can import the core module.
    thomas_pkg = types.ModuleType("thomas")
    channels_pkg = types.ModuleType("thomas.channels")
    cli_pkg = types.ModuleType("thomas.cli")
    commands_pkg = types.ModuleType("thomas.cli.commands")
    channel_ops_pkg = types.ModuleType("thomas.cli.commands.channel_ops")

    sys.modules.setdefault("thomas", thomas_pkg)
    sys.modules.setdefault("thomas.channels", channels_pkg)
    sys.modules.setdefault("thomas.cli", cli_pkg)
    sys.modules.setdefault("thomas.cli.commands", commands_pkg)
    sys.modules.setdefault("thomas.cli.commands.channel_ops", channel_ops_pkg)
    sys.modules["thomas.channels.p084_channel_resolve_command"] = core

    return _load_module(
        "thomas.cli.commands.channel_ops.p084_channel_resolve_command",
        "thomas/cli/commands/channel_ops/p084_channel_resolve_command.py",
    )


def test_resolve_telegram_username_success(core):
    req = core.ChannelResolveRequest(reference="@mychannel")
    resolver = _FakeTelegramResolver({"id": 123456789, "title": "My Channel", "username": "mychannel", "type": "channel"})

    result = core.resolve_channel(req, telegram_resolver=resolver)

    assert result.integration == "telegram"
    assert result.channel_id == "123456789"
    assert result.username in ("mychannel", "@mychannel")
    assert result.title == "My Channel"
    assert result.normalized_reference.startswith("telegram:")
    assert resolver.calls == ["@mychannel"]


def test_resolve_alias_from_config(core):
    cfg = {"channels": {"alerts": "telegram:@alerts_channel"}}
    req = core.ChannelResolveRequest(reference="alerts", config=cfg)
    resolver = _FakeTelegramResolver({"chat_id": -100555, "title": "Alerts", "username": "alerts_channel", "type": "supergroup"})

    result = core.resolve_channel(req, telegram_resolver=resolver)

    assert result.integration == "telegram"
    assert result.channel_id == "-100555"
    assert result.title == "Alerts"
    assert resolver.calls == ["@alerts_channel"]


def test_invalid_reference_empty(core):
    with pytest.raises(core.InvalidChannelReference) as ei:
        core.resolve_channel(core.ChannelResolveRequest(reference="   "), telegram_resolver=_FakeTelegramResolver({"id": 1}))
    assert ei.value.code == "INVALID_INPUT"
    assert ei.value.exit_code == 2


def test_missing_resolver_is_deterministic(core):
    with pytest.raises(core.MissingChannelConfig) as ei:
        core.resolve_channel(core.ChannelResolveRequest(reference="telegram:@x"), telegram_resolver=None)
    assert ei.value.code == "MISSING_CONFIG"
    assert ei.value.exit_code == 3
    assert ei.value.details.get("integration") == "telegram"


def test_external_failure_is_deterministic(core):
    class Boom:
        def get_chat(self, reference: str):
            raise RuntimeError("kaboom")

    with pytest.raises(core.ExternalChannelResolutionFailed) as ei:
        core.resolve_channel(core.ChannelResolveRequest(reference="@x"), telegram_resolver=Boom())
    assert ei.value.code == "EXTERNAL_FAILURE"
    assert ei.value.exit_code == 4
    assert ei.value.details.get("integration") == "telegram"


def test_cli_json_success(core):
    cli = _ensure_cli_loaded(core)

    resolver = _FakeTelegramResolver({"id": 42, "title": "The Answer", "username": "answer", "type": "private"})
    out = io.StringIO()
    err = io.StringIO()

    code = cli._run("@answer", json_output=True, config=None, telegram_resolver=resolver, out=out, err=err)
    assert code == 0
    assert err.getvalue() == ""

    payload = json.loads(out.getvalue())
    assert payload["ok"] is True
    assert payload["result"]["integration"] == "telegram"
    assert payload["result"]["channel_id"] == "42"


def test_cli_json_error(core):
    cli = _ensure_cli_loaded(core)

    out = io.StringIO()
    err = io.StringIO()

    code = cli._run("   ", json_output=True, telegram_resolver=_FakeTelegramResolver({"id": 1}), out=out, err=err)
    assert code == 2
    payload = json.loads(out.getvalue())
    assert payload["ok"] is False
    assert payload["error"]["code"] == "INVALID_INPUT"


def test_cli_json_schema_requires_no_reference(core):
    cli = _ensure_cli_loaded(core)

    out = io.StringIO()
    err = io.StringIO()

    code = cli._run(None, json_schema=True, out=out, err=err)
    assert code == 0
    assert err.getvalue() == ""

    payload = json.loads(out.getvalue())
    assert payload["ok"] is True
    assert "schema" in payload
    assert payload["schema"]["title"] == "ChannelResolveResult"
