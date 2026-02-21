from __future__ import annotations

import importlib
import inspect
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional, Set

CAPABILITIES_SCHEMA_VERSION = 1

# Thomas-native, provider-agnostic capability keys derived from integration surfaces.
_CAPABILITY_ALIASES: Dict[str, Set[str]] = {
    "send_text": {"send", "send_message", "send_text", "post_message"},
    "send_markdown": {"send_markdown", "send_md"},
    "send_image": {"send_image", "send_photo", "send_picture", "send_media"},
    "send_file": {"send_file", "send_document", "send_attachment"},
    "edit_message": {"edit_message", "edit_message_text", "update_message"},
    "delete_message": {"delete_message", "remove_message"},
    "reactions": {"add_reaction", "set_reaction", "react"},
    "typing_indicator": {"send_typing", "typing", "send_chat_action"},
    "threads": {"send_in_thread", "create_thread", "reply_in_thread"},
}


class ChannelCapabilitiesCommandError(Exception):
    def __init__(self, code: str, message: str, *, details: Optional[Dict[str, Any]] = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.details = details or None

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            out["details"] = dict(self.details)
        return out


@dataclass(frozen=True, slots=True)
class ChannelCapabilitiesRequest:
    channel: str


@dataclass(frozen=True, slots=True)
class ChannelCapabilitiesResult:
    schema_version: int
    channel: str
    integration: str
    capabilities: Dict[str, bool]
    native: Any = None
    details: Optional[Dict[str, Any]] = None

    def to_dict(self, *, ok: bool = True) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "ok": ok,
            "schema_version": self.schema_version,
            "channel": self.channel,
            "integration": self.integration,
            "capabilities": dict(self.capabilities),
        }
        if self.native is not None:
            payload["native"] = self.native
        if self.details:
            payload["details"] = dict(self.details)
        return payload

    def to_human_lines(self) -> Iterable[str]:
        yield f"Channel: {self.channel}"
        yield f"Integration: {self.integration}"
        yield "Capabilities:"
        for k in sorted(self.capabilities.keys()):
            yield f"  - {k}: {'yes' if self.capabilities[k] else 'no'}"


def get_channel_capabilities(request: ChannelCapabilitiesRequest, *, config: Any) -> ChannelCapabilitiesResult:
    channel = (request.channel or "").strip()
    if not channel:
        raise ChannelCapabilitiesCommandError("invalid_input", "Channel reference is required.")
    if config is None:
        raise ChannelCapabilitiesCommandError("missing_config", "No configuration object was provided.")

    channels_container = _get_channels_container(config)
    channel_cfg = _get_channel_entry(channels_container, channel)
    integration = _infer_integration(channel_cfg)

    module_name = f"thomas.integrations.{integration}"
    try:
        mod = importlib.import_module(module_name)
    except ModuleNotFoundError as e:
        raise ChannelCapabilitiesCommandError(
            "unknown_integration",
            f"No integration module found for '{integration}'.",
            details={"module": module_name},
        ) from e
    except Exception as e:  # pragma: no cover
        raise ChannelCapabilitiesCommandError(
            "external_failure",
            f"Failed to load integration '{integration}'.",
            details={"module": module_name, "reason": type(e).__name__},
        ) from e

    native = _get_native_capabilities(mod, channel_cfg)
    callables = _collect_callable_names(mod)
    derived = _derive_capabilities(callables)

    return ChannelCapabilitiesResult(
        schema_version=CAPABILITIES_SCHEMA_VERSION,
        channel=channel,
        integration=integration,
        capabilities=derived,
        native=native,
        details={"discovered_callables": sorted(callables)},
    )


def output_json_schema() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "ChannelCapabilitiesResult",
        "type": "object",
        "required": ["ok", "schema_version", "channel", "integration", "capabilities"],
        "properties": {
            "ok": {"type": "boolean"},
            "schema_version": {"type": "integer"},
            "channel": {"type": "string"},
            "integration": {"type": "string"},
            "capabilities": {"type": "object", "additionalProperties": {"type": "boolean"}},
            "native": {},
            "details": {"type": "object"},
        },
    }


def _get_channels_container(config: Any) -> Any:
    # Mapping forms.
    if isinstance(config, Mapping):
        for k in ("channels", "channel_configs", "messaging_channels"):
            if k in config:
                return config[k]
        # direct {channel: cfg} style
        return config

    # Attribute forms.
    for attr in ("channels", "channel_configs", "messaging_channels"):
        v = getattr(config, attr, None)
        if v is not None:
            return v

    getter = getattr(config, "get_channel", None)
    if callable(getter):
        return config

    raise ChannelCapabilitiesCommandError(
        "missing_config",
        "No channels configuration was found.",
        details={"expected": ["channels", "channel_configs", "messaging_channels", "get_channel"]},
    )


def _get_channel_entry(container: Any, channel: str) -> Any:
    if isinstance(container, Mapping):
        if channel in container:
            return container[channel]
        raise ChannelCapabilitiesCommandError("unknown_channel", f"Channel '{channel}' is not defined in configuration.")

    if hasattr(container, "get_channel") and callable(getattr(container, "get_channel")):
        try:
            return container.get_channel(channel)
        except Exception:
            raise ChannelCapabilitiesCommandError("unknown_channel", f"Channel '{channel}' is not defined in configuration.")

    if isinstance(container, (list, tuple)):
        for entry in container:
            name = _get(entry, "name") or _get(entry, "id") or _get(entry, "channel")
            if isinstance(name, str) and name == channel:
                return entry
        raise ChannelCapabilitiesCommandError("unknown_channel", f"Channel '{channel}' is not defined in configuration.")

    raise ChannelCapabilitiesCommandError(
        "missing_config",
        "Channels configuration is in an unsupported format.",
        details={"type": type(container).__name__},
    )


def _infer_integration(channel_cfg: Any) -> str:
    if isinstance(channel_cfg, str):
        v = channel_cfg.strip().lower()
        if v:
            return v

    for k in ("integration", "provider", "type", "kind", "platform", "service"):
        v = _get(channel_cfg, k)
        if isinstance(v, str) and v.strip():
            return v.strip().lower()

    nested = _get(channel_cfg, "integration")
    if nested is not None:
        v = _get(nested, "name") or _get(nested, "type") or _get(nested, "kind")
        if isinstance(v, str) and v.strip():
            return v.strip().lower()

    raise ChannelCapabilitiesCommandError(
        "missing_config",
        "Channel is missing an integration/type field.",
        details={"channel": repr(channel_cfg)},
    )


def _get(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, Mapping):
        return obj.get(key)
    return getattr(obj, key, None)


def _get_native_capabilities(mod: Any, channel_cfg: Any) -> Any:
    if hasattr(mod, "CAPABILITIES"):
        return getattr(mod, "CAPABILITIES")

    fn = getattr(mod, "get_capabilities", None) or getattr(mod, "capabilities", None)
    if not callable(fn):
        return None

    try:
        sig = inspect.signature(fn)
        if len(sig.parameters) == 0:
            return fn()
        return fn(channel_cfg)
    except TypeError:
        return fn()
    except Exception as e:
        raise ChannelCapabilitiesCommandError(
            "external_failure",
            f"Integration '{mod.__name__}' failed while resolving native capabilities.",
            details={"reason": type(e).__name__},
        ) from e


def _collect_callable_names(mod: Any) -> Set[str]:
    out: Set[str] = set()
    for name in dir(mod):
        if name.startswith("_"):
            continue
        try:
            attr = getattr(mod, name)
        except Exception:
            continue
        if callable(attr):
            out.add(name)
        if inspect.isclass(attr):
            for m in dir(attr):
                if m.startswith("_"):
                    continue
                try:
                    if callable(getattr(attr, m)):
                        out.add(m)
                except Exception:
                    continue
    return out


def _derive_capabilities(callable_names: Iterable[str]) -> Dict[str, bool]:
    present = set(callable_names)
    return {k: any(a in present for a in aliases) for k, aliases in _CAPABILITY_ALIASES.items()}
