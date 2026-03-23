import json
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

import thomas.marketplace.channels.p078_channel_add_command as channel_add_mod
from thomas.cli.commands.channel_ops.p078_channel_add_command import register as register_cli
from thomas.marketplace.channels.p078_channel_add_command import (
    ChannelAddConfigError,
    ChannelAddExternalError,
    ChannelAddRequest,
    add_channel,
)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_add_channel_success_writes_config(tmp_path: Path) -> None:
    cfg = tmp_path / "config.json"
    cfg.write_text("{}", encoding="utf-8")

    req = ChannelAddRequest(
        channel="telegram",
        token="123:abc",
        account="default",
        name="Alerts Bot",
        config_path=cfg,
        overwrite=False,
        verify=False,
    )
    res = add_channel(req)

    assert res.channel == "telegram"
    assert res.account == "default"
    assert res.config_path == cfg

    data = _read_json(cfg)
    assert data["channels"]["telegram"]["enabled"] is True
    assert data["channels"]["telegram"]["accounts"]["default"]["bot_token"] == "123:abc"
    assert data["channels"]["telegram"]["bot_token"] == "123:abc"


def test_add_channel_missing_config_file_is_deterministic(tmp_path: Path) -> None:
    cfg = tmp_path / "missing.json"
    req = ChannelAddRequest(channel="telegram", token="123:abc", config_path=cfg)
    with pytest.raises(ChannelAddConfigError) as ei:
        add_channel(req)
    assert ei.value.code == "config_missing"


def test_add_channel_duplicate_account_requires_overwrite(tmp_path: Path) -> None:
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps(
            {
                "channels": {
                    "telegram": {
                        "enabled": True,
                        "accounts": {"default": {"enabled": True, "bot_token": "old"}},
                        "bot_token": "old",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    req = ChannelAddRequest(channel="telegram", token="new", config_path=cfg, overwrite=False)
    with pytest.raises(ChannelAddConfigError) as ei:
        add_channel(req)
    assert ei.value.code == "account_exists"

    req2 = ChannelAddRequest(channel="telegram", token="new", config_path=cfg, overwrite=True)
    res2 = add_channel(req2)
    assert res2.overwritten is True
    data = _read_json(cfg)
    assert data["channels"]["telegram"]["accounts"]["default"]["bot_token"] == "new"
    assert data["channels"]["telegram"]["bot_token"] == "new"


def test_cli_json_success_and_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = typer.Typer()
    register_cli(app)
    runner = CliRunner()

    cfg = tmp_path / "config.json"
    cfg.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("THOMAS_CONFIG_PATH", str(cfg))

    ok = runner.invoke(app, ["add", "--channel", "telegram", "--token", "123:abc", "--json"])
    assert ok.exit_code == 0
    payload = json.loads(ok.stdout.strip())
    assert payload["ok"] is True
    assert payload["result"]["channel"] == "telegram"
    assert "123:abc" not in ok.stdout

    missing = tmp_path / "missing.json"
    monkeypatch.setenv("THOMAS_CONFIG_PATH", str(missing))
    bad = runner.invoke(app, ["add", "--channel", "telegram", "--token", "123:abc", "--json"])
    assert bad.exit_code != 0
    payload2 = json.loads(bad.stdout.strip())
    assert payload2["ok"] is False
    assert payload2["error"]["code"] == "config_missing"


def test_cli_json_invalid_input_is_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = typer.Typer()
    register_cli(app)
    runner = CliRunner()

    cfg = tmp_path / "config.json"
    cfg.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("THOMAS_CONFIG_PATH", str(cfg))

    bad = runner.invoke(app, ["add", "--channel", "telegram", "--json"])
    assert bad.exit_code != 0
    payload = json.loads(bad.stdout.strip())
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_input"


def test_add_channel_write_failure_is_deterministic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "config.json"
    cfg.write_text("{}", encoding="utf-8")

    def _boom(src: str, dst: str) -> None:  # pragma: no cover
        raise OSError("simulated write failure")

    monkeypatch.setattr(channel_add_mod.os, "replace", _boom)

    req = ChannelAddRequest(channel="telegram", token="123:abc", config_path=cfg)
    with pytest.raises(ChannelAddExternalError) as ei:
        add_channel(req)
    assert ei.value.code == "config_write_failed"
