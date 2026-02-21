import json
from pathlib import Path

import pytest

from thomas.channels.p076_channel_registry_loader import (
    ChannelRegistryLoadRequest,
    ChannelRegistryNotFoundError,
    ChannelRegistryParseError,
    ChannelRegistryValidationError,
    load_channel_registry,
    channel_registry_load_result_schema,
)


def test_load_registry_yaml_success(tmp_path: Path) -> None:
    registry = tmp_path / "channels.yaml"
    registry.write_text(
        '''
version: 1
channels:
  - name: alerts
    kind: telegram
    config:
      token: ${BOT_TOKEN}
      chat_id: ${CHAT_ID}
  - name: audit
    kind: webhook
    url: https://example.test/hook
'''.lstrip(),
        encoding="utf-8",
    )

    result = load_channel_registry(
        ChannelRegistryLoadRequest(
            registry_path=registry,
            env={"BOT_TOKEN": "tkn", "CHAT_ID": "123"},
            strict=True,
        )
    )

    assert result.source_path.endswith("channels.yaml")
    assert [c.name for c in result.channels] == ["alerts", "audit"]
    alerts = result.channels[0]
    assert alerts.kind == "telegram"
    assert alerts.config["token"] == "tkn"
    assert alerts.config["chat_id"] == "123"


def test_shorthand_mapping_allows_metadata_keys(tmp_path: Path) -> None:
    registry = tmp_path / "channels.yaml"
    registry.write_text(
        '''
version: 1
schema: 1
alerts:
  kind: telegram
  token: ${BOT_TOKEN}
  chat_id: ${CHAT_ID}
'''.lstrip(),
        encoding="utf-8",
    )

    result = load_channel_registry(
        ChannelRegistryLoadRequest(
            registry_path=registry,
            env={"BOT_TOKEN": "tkn", "CHAT_ID": "123"},
            strict=True,
        )
    )
    assert [c.name for c in result.channels] == ["alerts"]
    assert result.channels[0].config["token"] == "tkn"


def test_load_registry_missing_file_is_deterministic(tmp_path: Path) -> None:
    missing = tmp_path / "nope.yaml"
    with pytest.raises(ChannelRegistryNotFoundError) as exc:
        load_channel_registry(ChannelRegistryLoadRequest(registry_path=missing, env={}, strict=True))

    assert exc.value.code == "channel_registry_not_found"
    assert str(missing) in str(exc.value)


def test_load_registry_invalid_yaml_raises_parse_error(tmp_path: Path) -> None:
    bad = tmp_path / "channels.yaml"
    bad.write_text("channels: [:", encoding="utf-8")

    with pytest.raises(ChannelRegistryParseError) as exc:
        load_channel_registry(ChannelRegistryLoadRequest(registry_path=bad, env={}, strict=True))

    assert exc.value.code == "channel_registry_parse_error"
    assert "Failed to parse" in str(exc.value)


def test_load_registry_missing_env_var_raises_validation_error(tmp_path: Path) -> None:
    registry = tmp_path / "channels.yaml"
    registry.write_text(
        '''
channels:
  - name: alerts
    kind: telegram
    config:
      token: ${MISSING_TOKEN}
      chat_id: 1
'''.lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(ChannelRegistryValidationError) as exc:
        load_channel_registry(ChannelRegistryLoadRequest(registry_path=registry, env={}, strict=True))

    assert exc.value.code == "channel_registry_validation_error"
    assert exc.value.details.get("missing_env") == ["MISSING_TOKEN"]


def test_schema_is_valid_json() -> None:
    schema = channel_registry_load_result_schema()
    json.dumps(schema)
