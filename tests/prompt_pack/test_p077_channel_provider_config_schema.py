from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, TypedDict

import pytest

from thomas.channels.p077_channel_provider_config_schema import (
    ChannelProviderNotFoundError,
    InvalidProviderNameError,
    json_schema_from_type,
    get_channel_provider_config_schema,
)


def test_json_schema_from_dataclass_required_and_optional() -> None:
    @dataclass
    class Example:
        token: str
        chat_id: int
        timeout: Optional[int] = None

    schema = json_schema_from_type(Example)
    assert schema["type"] == "object"
    assert set(schema["properties"].keys()) == {"token", "chat_id", "timeout"}
    assert set(schema.get("required", [])) == {"token", "chat_id"}
    assert "timeout" not in schema.get("required", [])


def test_json_schema_from_typed_dict_required_and_optional() -> None:
    class Example(TypedDict):
        token: str
        chat_id: int

    schema = json_schema_from_type(Example)
    assert schema["type"] == "object"
    assert set(schema["properties"].keys()) == {"token", "chat_id"}
    assert set(schema.get("required", [])) == {"token", "chat_id"}


def test_invalid_provider_name_is_deterministic() -> None:
    with pytest.raises(InvalidProviderNameError) as ei:
        get_channel_provider_config_schema("not valid")
    err = ei.value
    assert err.code == "INVALID_PROVIDER_NAME"
    d = err.to_dict()
    assert d["code"] == "INVALID_PROVIDER_NAME"
    assert "message" in d


def test_unknown_provider_is_deterministic() -> None:
    with pytest.raises(ChannelProviderNotFoundError) as ei:
        get_channel_provider_config_schema("definitely_not_a_real_provider_abc123")
    err = ei.value
    assert err.code == "PROVIDER_NOT_FOUND"
    d = err.to_dict()
    assert d["code"] == "PROVIDER_NOT_FOUND"
    assert "attempted_modules" in d.get("details", {})
