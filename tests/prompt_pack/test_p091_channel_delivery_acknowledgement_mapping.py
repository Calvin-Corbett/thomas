import json
from pathlib import Path

import pytest

from thomas.cli.commands.channel_ops.p091_channel_delivery_acknowledgement_mapping import (
    run_delivery_ack_mapping,
)
from thomas.marketplace.channels.p091_channel_delivery_acknowledgement_mapping import (
    ChannelDeliveryAckMappingRequest,
    ConfigInvalidError,
    ConfigNotFoundError,
    InvalidInputError,
    build_channel_delivery_ack_mapping,
    build_mapping_from_channels,
)


def test_mapping_explicit_channels_success() -> None:
    resp = build_mapping_from_channels(["telegram", "slack", "discord", "google-chat"])

    assert resp.source == "explicit"
    assert resp.channels == ["telegram", "slack", "discord", "googlechat"]

    assert resp.mapping["telegram"].supported is True
    assert resp.mapping["telegram"].ack_handle_kind == "message_id"
    assert resp.mapping["telegram"].ack_handle_value_type == "int"
    assert resp.mapping["telegram"].ack_handle_fields == ["message_id"]
    assert resp.mapping["telegram"].marker_mechanism == "reaction"

    assert resp.mapping["slack"].ack_handle_kind == "timestamp"
    assert resp.mapping["slack"].ack_handle_fields == ["ts"]
    assert resp.mapping["slack"].marker_value_format == "slack_shortcode"

    assert resp.mapping["discord"].ack_handle_kind == "message_id"
    assert resp.mapping["discord"].marker_value_format == "discord_emoji"


def test_mapping_unknown_channel_strict_raises() -> None:
    with pytest.raises(InvalidInputError) as exc:
        build_mapping_from_channels(["totally-not-a-channel"], strict=True)

    assert exc.value.code == "INVALID_INPUT"
    assert exc.value.details.get("canonical") == "totally-not-a-channel"


def test_mapping_config_path_missing_is_deterministic(tmp_path: Path) -> None:
    missing = tmp_path / "nope.json"
    req = ChannelDeliveryAckMappingRequest(channels=None, config_path=str(missing))

    with pytest.raises(ConfigNotFoundError) as exc:
        build_channel_delivery_ack_mapping(req)

    assert exc.value.code == "CONFIG_NOT_FOUND"
    assert exc.value.details.get("path") == str(missing)


def test_mapping_config_path_invalid_json_is_deterministic(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json}", encoding="utf-8")

    req = ChannelDeliveryAckMappingRequest(channels=None, config_path=str(bad))
    with pytest.raises(ConfigInvalidError) as exc:
        build_channel_delivery_ack_mapping(req)

    assert exc.value.code == "CONFIG_INVALID"
    assert exc.value.details.get("path") == str(bad)


def test_cli_runner_json_success(capsys: pytest.CaptureFixture[str]) -> None:
    code = run_delivery_ack_mapping(channels=["telegram", "slack"], json_output=True)
    assert code == 0

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["source"] == "explicit"
    assert payload["mapping"]["telegram"]["ack_handle_kind"] == "message_id"
    assert payload["mapping"]["slack"]["ack_handle_fields"] == ["ts"]


def test_cli_runner_json_failure(capsys: pytest.CaptureFixture[str]) -> None:
    code = run_delivery_ack_mapping(channels=["nope"], json_output=True)
    assert code == 2

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "INVALID_INPUT"
