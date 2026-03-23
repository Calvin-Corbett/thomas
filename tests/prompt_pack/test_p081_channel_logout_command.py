import json
from pathlib import Path

import pytest

from thomas.cli.commands.channel_ops import p081_channel_logout_command as cli_mod
from thomas.marketplace.channels.p081_channel_logout_command import (
    ChannelLogoutError,
    ChannelLogoutRequest,
    error_to_json,
    logout_channel,
    logout_result_to_json,
)


def test_logout_channel_success_deletes_config(tmp_path: Path) -> None:
    channels_dir = tmp_path / "channels"
    channels_dir.mkdir()
    state_file = channels_dir / "telegram.json"
    state_file.write_text('{"token": "abc"}', encoding="utf-8")

    result = logout_channel(
        ChannelLogoutRequest(
            channel="telegram",
            config_root=tmp_path,
            call_integration_hooks=False,
            include_integration_hints=False,
        )
    )

    assert result.channel == "telegram"
    assert str(state_file) in result.removed
    assert result.dry_run is False
    assert not state_file.exists()


def test_logout_channel_dry_run_does_not_delete(tmp_path: Path) -> None:
    channels_dir = tmp_path / "channels"
    channels_dir.mkdir()
    state_file = channels_dir / "telegram.json"
    state_file.write_text('{"token": "abc"}', encoding="utf-8")

    result = logout_channel(
        ChannelLogoutRequest(
            channel="telegram",
            config_root=tmp_path,
            dry_run=True,
            call_integration_hooks=False,
            include_integration_hints=False,
        )
    )

    assert str(state_file) in result.removed
    assert result.dry_run is True
    assert state_file.exists()


def test_logout_channel_missing_state_is_deterministic_error(tmp_path: Path) -> None:
    with pytest.raises(ChannelLogoutError) as exc:
        logout_channel(
            ChannelLogoutRequest(
                channel="telegram",
                config_root=tmp_path,
                call_integration_hooks=False,
                include_integration_hints=False,
            )
        )
    assert exc.value.code == "not_logged_in"


def test_logout_channel_invalid_input_is_deterministic_error(tmp_path: Path) -> None:
    with pytest.raises(ChannelLogoutError) as exc:
        logout_channel(ChannelLogoutRequest(channel="   ", config_root=tmp_path))
    assert exc.value.code == "invalid_input"


def test_json_helpers_are_machine_readable(tmp_path: Path) -> None:
    channels_dir = tmp_path / "channels"
    channels_dir.mkdir()
    state_file = channels_dir / "telegram.json"
    state_file.write_text('{"token": "abc"}', encoding="utf-8")

    result = logout_channel(
        ChannelLogoutRequest(
            channel="telegram",
            config_root=tmp_path,
            call_integration_hooks=False,
            include_integration_hints=False,
        )
    )
    payload = logout_result_to_json(result)
    assert payload["ok"] is True
    assert payload["channel"] == "telegram"
    assert payload["dry_run"] is False
    assert str(state_file) in payload["removed"]

    err_payload = error_to_json(ChannelLogoutError("x", "y"))
    assert err_payload["ok"] is False
    assert err_payload["error"]["code"] == "x"


def test_cli_logout_json_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import typer
    from typer.testing import CliRunner

    app = typer.Typer()
    cli_mod.register(app)

    channels_dir = tmp_path / "channels"
    channels_dir.mkdir()
    (channels_dir / "telegram.json").write_text('{"token": "abc"}', encoding="utf-8")
    monkeypatch.setenv("THOMAS_CONFIG_DIR", str(tmp_path))

    runner = CliRunner()
    result = runner.invoke(app, ["logout", "telegram", "--json"])
    assert result.exit_code == 0

    data = json.loads(result.stdout)
    assert data["ok"] is True
    assert data["channel"] == "telegram"
    assert isinstance(data["removed"], list)


def test_cli_logout_json_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import typer
    from typer.testing import CliRunner

    app = typer.Typer()
    cli_mod.register(app)

    monkeypatch.setenv("THOMAS_CONFIG_DIR", str(tmp_path))

    runner = CliRunner()
    result = runner.invoke(app, ["logout", "telegram", "--json"])
    assert result.exit_code != 0

    data = json.loads(result.stdout)
    assert data["ok"] is False
    assert data["error"]["code"] in {"not_logged_in", "missing_config"}
