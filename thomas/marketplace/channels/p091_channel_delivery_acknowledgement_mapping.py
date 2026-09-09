from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

# "Delivery acknowledgement" here means: when Thomas posts a message through a channel
# integration, what identifier(s) are returned that let Thomas refer back to that
# specific remote message later.
#
# Example:
# - Telegram: message_id (int)
# - Slack: ts (timestamp token string)
# - Discord: message_id (string)
#
# Separately, some channels also allow a *marker* for "delivered" via a reaction.


AckHandleKind = Literal["message_id", "timestamp", "resource_name", "none", "unknown"]
AckHandleValueType = Literal["int", "string", "object", "none", "unknown"]

MarkerMechanism = Literal["reaction", "none", "unknown"]
MarkerValueFormat = Literal[
    "unicode_emoji",  # unicode emoji character(s)
    "slack_shortcode",  # Slack reaction name, e.g. eyes (no colons)
    "discord_emoji",  # unicode emoji or custom emoji in the form name:id
    "none",
    "unknown",
]


class ChannelDeliveryAckMappingError(Exception):
    """Deterministic, machine-readable failures for delivery acknowledgement mapping."""

    code: str
    details: dict[str, Any]

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error": {
                "code": self.code,
                "message": str(self),
                "details": self.details,
            },
        }


class InvalidInputError(ChannelDeliveryAckMappingError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__("INVALID_INPUT", message, details=details)


class ConfigNotFoundError(ChannelDeliveryAckMappingError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__("CONFIG_NOT_FOUND", message, details=details)


class ConfigInvalidError(ChannelDeliveryAckMappingError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__("CONFIG_INVALID", message, details=details)


@dataclass(frozen=True)
class ChannelDeliveryAckSpec:
    """Per-channel acknowledgement mapping.

    - ack_handle_* describes the provider-native identifier(s) returned on successful post.
    - marker_* describes how Thomas can visually mark delivery (if supported).
    """

    channel: str
    supported: bool

    ack_handle_kind: AckHandleKind
    ack_handle_value_type: AckHandleValueType
    # Provider-native field(s) that make up the handle (e.g. ["message_id"], ["ts"]).
    ack_handle_fields: list[str]

    marker_mechanism: MarkerMechanism
    marker_value_format: MarkerValueFormat
    marker_supports_removal: bool

    notes: str = ""


@dataclass(frozen=True)
class ChannelDeliveryAckMappingRequest:
    """Input contract for mapping generation."""

    # If provided, mapping is generated for exactly these channels.
    channels: Sequence[str] | None = None

    # Optional already-parsed config.
    config: Mapping[str, Any] | None = None

    # Optional config path to load if `config` is not provided.
    config_path: str | None = None

    # When True and `channels` is provided, unknown channel names raise.
    strict: bool = True


@dataclass(frozen=True)
class ChannelDeliveryAckMappingResponse:
    """Output contract for mapping generation."""

    source: Literal["explicit", "config"]
    channels: list[str]
    mapping: dict[str, ChannelDeliveryAckSpec]
    schema_version: str = "1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "schema_version": self.schema_version,
            "source": self.source,
            "channels": list(self.channels),
            "mapping": {k: asdict(v) for k, v in self.mapping.items()},
        }


def response_json_schema() -> dict[str, Any]:
    """A minimal JSON schema for automation."""

    return {
        "type": "object",
        "required": ["ok"],
        "properties": {
            "ok": {"type": "boolean"},
            "schema_version": {"type": "string"},
            "source": {"type": "string", "enum": ["explicit", "config"]},
            "channels": {"type": "array", "items": {"type": "string"}},
            "mapping": {
                "type": "object",
                "additionalProperties": {
                    "type": "object",
                    "required": [
                        "channel",
                        "supported",
                        "ack_handle_kind",
                        "ack_handle_value_type",
                        "ack_handle_fields",
                        "marker_mechanism",
                        "marker_value_format",
                        "marker_supports_removal",
                        "notes",
                    ],
                    "properties": {
                        "channel": {"type": "string"},
                        "supported": {"type": "boolean"},
                        "ack_handle_kind": {"type": "string"},
                        "ack_handle_value_type": {"type": "string"},
                        "ack_handle_fields": {"type": "array", "items": {"type": "string"}},
                        "marker_mechanism": {"type": "string"},
                        "marker_value_format": {"type": "string"},
                        "marker_supports_removal": {"type": "boolean"},
                        "notes": {"type": "string"},
                    },
                },
            },
            "error": {
                "type": "object",
                "required": ["code", "message"],
                "properties": {
                    "code": {"type": "string"},
                    "message": {"type": "string"},
                    "details": {"type": "object"},
                },
            },
        },
    }


_CHANNEL_ALIASES: dict[str, str] = {
    "google_chat": "googlechat",
    "google-chat": "googlechat",
    "gchat": "googlechat",
    "ms_teams": "msteams",
    "ms-teams": "msteams",
    "teams": "msteams",
    "googlechat": "googlechat",
    "slack": "slack",
    "discord": "discord",
    "telegram": "telegram",
    "email": "email",
    "sms": "sms",
    "signal": "signal",
    "whatsapp": "whatsapp",
    "imessage": "imessage",
}


def _canonicalize_channel(name: str) -> str:
    raw = name.strip().lower()
    if not raw:
        return raw
    raw = raw.replace(" ", "")
    if raw in _CHANNEL_ALIASES:
        return _CHANNEL_ALIASES[raw]
    soft = raw.replace("-", "").replace("_", "")
    if soft in _CHANNEL_ALIASES:
        return _CHANNEL_ALIASES[soft]
    return raw


_KNOWN_SPECS: dict[str, ChannelDeliveryAckSpec] = {
    "telegram": ChannelDeliveryAckSpec(
        channel="telegram",
        supported=True,
        ack_handle_kind="message_id",
        ack_handle_value_type="int",
        ack_handle_fields=["message_id"],
        marker_mechanism="reaction",
        marker_value_format="unicode_emoji",
        marker_supports_removal=True,
        notes="Telegram send returns message_id; reactions use unicode emoji.",
    ),
    "slack": ChannelDeliveryAckSpec(
        channel="slack",
        supported=True,
        ack_handle_kind="timestamp",
        ack_handle_value_type="string",
        ack_handle_fields=["ts"],
        marker_mechanism="reaction",
        marker_value_format="slack_shortcode",
        marker_supports_removal=True,
        notes="Slack send returns ts; reactions are referenced by name (no surrounding colons).",
    ),
    "discord": ChannelDeliveryAckSpec(
        channel="discord",
        supported=True,
        ack_handle_kind="message_id",
        ack_handle_value_type="string",
        ack_handle_fields=["message_id"],
        marker_mechanism="reaction",
        marker_value_format="discord_emoji",
        marker_supports_removal=True,
        notes="Discord send returns message_id; reactions accept unicode emoji or custom 'name:id'.",
    ),
    "googlechat": ChannelDeliveryAckSpec(
        channel="googlechat",
        supported=True,
        ack_handle_kind="resource_name",
        ack_handle_value_type="string",
        ack_handle_fields=["name"],
        marker_mechanism="reaction",
        marker_value_format="unicode_emoji",
        marker_supports_removal=True,
        notes="Google Chat APIs typically return a message resource name; reactions are unicode emoji.",
    ),
    # Conservative defaults for channels without Thomas support.
    "msteams": ChannelDeliveryAckSpec(
        channel="msteams",
        supported=False,
        ack_handle_kind="unknown",
        ack_handle_value_type="unknown",
        ack_handle_fields=[],
        marker_mechanism="none",
        marker_value_format="none",
        marker_supports_removal=False,
        notes="No delivery acknowledgement mapping is defined for this channel in Thomas.",
    ),
    "whatsapp": ChannelDeliveryAckSpec(
        channel="whatsapp",
        supported=False,
        ack_handle_kind="unknown",
        ack_handle_value_type="unknown",
        ack_handle_fields=[],
        marker_mechanism="none",
        marker_value_format="none",
        marker_supports_removal=False,
        notes="No delivery acknowledgement mapping is defined for this channel in Thomas.",
    ),
    "signal": ChannelDeliveryAckSpec(
        channel="signal",
        supported=False,
        ack_handle_kind="unknown",
        ack_handle_value_type="unknown",
        ack_handle_fields=[],
        marker_mechanism="none",
        marker_value_format="none",
        marker_supports_removal=False,
        notes="No delivery acknowledgement mapping is defined for this channel in Thomas.",
    ),
    "imessage": ChannelDeliveryAckSpec(
        channel="imessage",
        supported=False,
        ack_handle_kind="unknown",
        ack_handle_value_type="unknown",
        ack_handle_fields=[],
        marker_mechanism="none",
        marker_value_format="none",
        marker_supports_removal=False,
        notes="No delivery acknowledgement mapping is defined for this channel in Thomas.",
    ),
    "sms": ChannelDeliveryAckSpec(
        channel="sms",
        supported=False,
        ack_handle_kind="none",
        ack_handle_value_type="none",
        ack_handle_fields=[],
        marker_mechanism="none",
        marker_value_format="none",
        marker_supports_removal=False,
        notes="No delivery acknowledgement mapping is defined for this channel in Thomas.",
    ),
    "email": ChannelDeliveryAckSpec(
        channel="email",
        supported=False,
        ack_handle_kind="none",
        ack_handle_value_type="none",
        ack_handle_fields=[],
        marker_mechanism="none",
        marker_value_format="none",
        marker_supports_removal=False,
        notes="No delivery acknowledgement mapping is defined for this channel in Thomas.",
    ),
}


def _default_config_paths() -> list[Path]:
    """Candidate config paths.

    Keep this small and deterministic.
    """

    candidates: list[Path] = []
    for var in ("THOMAS_CONFIG_PATH", "THOMAS_CONFIG_FILE", "THOMAS_CONFIG"):
        val = os.environ.get(var)
        if val:
            candidates.append(Path(val).expanduser())
    candidates.extend(
        [
            Path.cwd() / "thomas.json",
            Path.cwd() / "thomas.config.json",
            Path("~/.thomas/config.json").expanduser(),
            Path("~/.config/thomas/config.json").expanduser(),
        ]
    )

    seen: set[str] = set()
    out: list[Path] = []
    for p in candidates:
        key = str(p)
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def _load_json_file(path: Path) -> Mapping[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise ConfigNotFoundError("Configuration file not found.", details={"path": str(path)}) from e
    except OSError as e:
        raise ConfigInvalidError(
            "Failed to read configuration file.",
            details={"path": str(path), "error": type(e).__name__},
        ) from e

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise ConfigInvalidError(
            "Configuration file is not valid JSON.",
            details={"path": str(path), "line": e.lineno, "col": e.colno},
        ) from e

    if not isinstance(parsed, dict):
        raise ConfigInvalidError(
            "Configuration root must be a JSON object.",
            details={"path": str(path), "type": type(parsed).__name__},
        )
    return parsed


def _extract_channels_from_config(config: Mapping[str, Any]) -> list[str]:
    channels_obj = config.get("channels")
    if channels_obj is None:
        raise ConfigInvalidError(
            "Configuration is missing required 'channels' object.",
            details={"missing": "channels"},
        )
    if not isinstance(channels_obj, dict):
        raise ConfigInvalidError(
            "Configuration field 'channels' must be an object.",
            details={"type": type(channels_obj).__name__},
        )

    keys = [k for k in channels_obj.keys() if isinstance(k, str) and k.strip()]
    if not keys:
        raise ConfigInvalidError("No channels are configured.", details={"channels": []})
    return keys


def build_channel_delivery_ack_mapping(
    request: ChannelDeliveryAckMappingRequest,
) -> ChannelDeliveryAckMappingResponse:
    """Build a per-channel delivery acknowledgement mapping."""

    if request.channels is not None:
        source: Literal["explicit", "config"] = "explicit"
        if isinstance(request.channels, (str, bytes)):
            raise InvalidInputError("'channels' must be a sequence of strings, not a string.")
        raw_channels = list(request.channels)
        if not raw_channels:
            raise InvalidInputError("'channels' cannot be empty.")
    else:
        source = "config"
        if request.config is not None:
            config = request.config
        else:
            config_path = Path(request.config_path).expanduser() if request.config_path else None
            loaded: Mapping[str, Any] | None = None
            if config_path is not None:
                loaded = _load_json_file(config_path)
            else:
                last_missing: ConfigNotFoundError | None = None
                for candidate in _default_config_paths():
                    try:
                        loaded = _load_json_file(candidate)
                        break
                    except ConfigNotFoundError as e:
                        last_missing = e
                if loaded is None:
                    raise last_missing or ConfigNotFoundError("No configuration file found.")
            config = loaded

        raw_channels = _extract_channels_from_config(config)

    mapping: dict[str, ChannelDeliveryAckSpec] = {}
    canonical_channels: list[str] = []

    for raw in raw_channels:
        if not isinstance(raw, str):
            raise InvalidInputError(
                "Channel identifiers must be strings.",
                details={"value": repr(raw), "type": type(raw).__name__},
            )

        canon = _canonicalize_channel(raw)
        if not canon:
            raise InvalidInputError("Channel identifier cannot be blank.")
        if canon in mapping:
            continue

        spec = _KNOWN_SPECS.get(canon)
        if spec is None:
            if source == "explicit" and request.strict:
                raise InvalidInputError("Unknown channel.", details={"channel": raw, "canonical": canon})
            spec = ChannelDeliveryAckSpec(
                channel=canon,
                supported=False,
                ack_handle_kind="unknown",
                ack_handle_value_type="unknown",
                ack_handle_fields=[],
                marker_mechanism="unknown",
                marker_value_format="unknown",
                marker_supports_removal=False,
                notes="Unknown channel; acknowledgement mapping is not defined.",
            )

        mapping[canon] = spec
        canonical_channels.append(canon)

    return ChannelDeliveryAckMappingResponse(source=source, channels=canonical_channels, mapping=mapping)


def build_mapping_from_channels(
    channels: Sequence[str],
    *,
    strict: bool = True,
) -> ChannelDeliveryAckMappingResponse:
    """Convenience wrapper for explicit channel lists."""

    return build_channel_delivery_ack_mapping(ChannelDeliveryAckMappingRequest(channels=list(channels), strict=strict))
