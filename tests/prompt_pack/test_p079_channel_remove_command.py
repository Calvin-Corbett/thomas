import json
from pathlib import Path
import os
import pytest

from thomas.channels.p079_channel_remove_command import (
    ChannelRemoveError,
    ChannelRemoveErrorCode,
    ChannelRemoveRequest,
    remove_channel,
)

from thomas.cli.commands.channel_ops.p079_channel_remove_command import run_channel_remove


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_remove_disables_channel_by_default(tmp_path: Path):
    cfg_path = tmp_path / "config.json"
    _write_json(cfg_path, {"channels": {"telegram": {"enabled": True, "botToken": "x"}}})

    res = remove_channel(ChannelRemoveRequest(channel="telegram", delete=False, config_path=cfg_path))

    assert res.channel == "telegram"
    assert res.account == "default"
    assert res.action == "disabled"
    assert res.changed is True

    cfg = _read_json(cfg_path)
    assert cfg["channels"]["telegram"]["enabled"] is False


def test_remove_disable_is_idempotent(tmp_path: Path):
    cfg_path = tmp_path / "config.json"
    _write_json(cfg_path, {"channels": {"telegram": {"enabled": False}}})

    res = remove_channel(ChannelRemoveRequest(channel="telegram", delete=False, config_path=cfg_path))

    assert res.action == "disabled"
    assert res.changed is False


def test_remove_delete_removes_channel_entry(tmp_path: Path):
    cfg_path = tmp_path / "config.json"
    _write_json(cfg_path, {"channels": {"telegram": {"enabled": True}, "discord": {"enabled": True}}})

    res = remove_channel(ChannelRemoveRequest(channel="telegram", delete=True, config_path=cfg_path))

    assert res.action == "deleted"

    cfg = _read_json(cfg_path)
    assert "telegram" not in cfg["channels"]
    assert "discord" in cfg["channels"]


def test_remove_disables_named_account(tmp_path: Path):
    cfg_path = tmp_path / "config.json"
    _write_json(
        cfg_path,
        {"channels": {"telegram": {"accounts": {"acct1": {"enabled": True, "botToken": "x"}}}}},
    )

    res = remove_channel(ChannelRemoveRequest(channel="telegram", account="acct1", delete=False, config_path=cfg_path))
    assert res.account == "acct1"
    assert res.action == "disabled"

    cfg = _read_json(cfg_path)
    assert cfg["channels"]["telegram"]["accounts"]["acct1"]["enabled"] is False


def test_remove_deletes_named_account(tmp_path: Path):
    cfg_path = tmp_path / "config.json"
    _write_json(
        cfg_path,
        {"channels": {"telegram": {"accounts": {"acct1": {"enabled": True}, "acct2": {"enabled": True}}}}},
    )

    res = remove_channel(ChannelRemoveRequest(channel="telegram", account="acct1", delete=True, config_path=cfg_path))
    assert res.action == "deleted"

    cfg = _read_json(cfg_path)
    assert "acct1" not in cfg["channels"]["telegram"]["accounts"]
    assert "acct2" in cfg["channels"]["telegram"]["accounts"]


def test_remove_unknown_channel_errors(tmp_path: Path):
    cfg_path = tmp_path / "config.json"
    _write_json(cfg_path, {"channels": {"discord": {"enabled": True}}})

    with pytest.raises(ChannelRemoveError) as ei:
        remove_channel(ChannelRemoveRequest(channel="telegram", delete=True, config_path=cfg_path))

    assert ei.value.code == ChannelRemoveErrorCode.CHANNEL_NOT_FOUND


def test_remove_unknown_account_errors(tmp_path: Path):
    cfg_path = tmp_path / "config.json"
    _write_json(cfg_path, {"channels": {"telegram": {"accounts": {"acct1": {"enabled": True}}}}})

    with pytest.raises(ChannelRemoveError) as ei:
        remove_channel(ChannelRemoveRequest(channel="telegram", account="acctX", delete=False, config_path=cfg_path))

    assert ei.value.code == ChannelRemoveErrorCode.ACCOUNT_NOT_FOUND


def test_remove_missing_config_file_errors(tmp_path: Path):
    cfg_path = tmp_path / "missing.json"

    with pytest.raises(ChannelRemoveError) as ei:
        remove_channel(ChannelRemoveRequest(channel="telegram", config_path=cfg_path))

    assert ei.value.code == ChannelRemoveErrorCode.CONFIG_NOT_FOUND


def test_cli_json_output_on_error(tmp_path: Path, capsys):
    cfg_path = tmp_path / "config.json"
    _write_json(cfg_path, {"channels": {"discord": {"enabled": True}}})

    os.environ["THOMAS_CONFIG_PATH"] = str(cfg_path)
    try:
        code = run_channel_remove(channel="telegram", delete=False, json_output=True)
    finally:
        os.environ.pop("THOMAS_CONFIG_PATH", None)

    assert code != 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "CHANNEL_NOT_FOUND"
