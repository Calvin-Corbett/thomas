from __future__ import annotations

"""Channel integration into the Thomas channels module.

This module provides a small, typed API for validating and enabling messaging
channels (initially: Telegram) in a Thomas configuration file.

It is intentionally conservative:
- deterministic error codes for automation
- no network calls unless explicitly requested (test_message / validate_external)
- flexible config discovery (multiple common layouts are supported)
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

# -----------------------------
# Deterministic errors
# -----------------------------


class ChannelIntegrationError(RuntimeError):
    """Deterministic error with a stable machine-readable code."""

    def __init__(self, *, code: str, message: str, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: dict[str, Any] = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class InvalidInputError(ChannelIntegrationError):
    def __init__(self, message: str, details: Mapping[str, Any] | None = None):
        super().__init__(code="invalid_input", message=message, details=details)


class MissingConfigError(ChannelIntegrationError):
    def __init__(self, message: str, details: Mapping[str, Any] | None = None):
        super().__init__(code="missing_config", message=message, details=details)


class ExternalFailureError(ChannelIntegrationError):
    def __init__(self, message: str, details: Mapping[str, Any] | None = None):
        super().__init__(code="external_failure", message=message, details=details)


# -----------------------------
# Typed contracts
# -----------------------------


@dataclass(frozen=True)
class ChannelIntegrationRequest:
    """Input contract for integrating a channel provider."""

    provider: str
    # You may provide either a config_path (preferred for persistence) or a config mapping.
    config_path: Path | None = None
    config: Mapping[str, Any] | None = None

    # Persist enablement into the config file (requires config_path). If False, validate only.
    persist_enablement: bool = True

    # If True, compute/validate but do not write any changes.
    dry_run: bool = False

    # If provided, attempt to send this message via the provider (network call).
    test_message: str | None = None

    # If True, attempt a lightweight provider validation (may call into integration module).
    validate_external: bool = False


@dataclass(frozen=True)
class ChannelIntegrationResult:
    """Output contract for channel integration."""

    provider: str
    integrated: bool
    validated: bool
    wrote_config: bool
    config_path: str | None = None
    enabled_channels: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "integrated": self.integrated,
            "validated": self.validated,
            "wrote_config": self.wrote_config,
            "config_path": self.config_path,
            "enabled_channels": self.enabled_channels,
            "details": self.details,
            "warnings": self.warnings,
        }


class TelegramSender(Protocol):
    """Small interface for sending Telegram messages (DI-friendly)."""

    def send_message(self, *, token: str, chat_id: str, text: str) -> Mapping[str, Any]: ...


# -----------------------------
# Config helpers
# -----------------------------


_SUPPORTED_PROVIDERS: tuple[str, ...] = ("telegram",)


def supported_providers() -> tuple[str, ...]:
    return _SUPPORTED_PROVIDERS


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise MissingConfigError("Config file not found.", details={"path": str(path)}) from e
    except OSError as e:
        raise ExternalFailureError("Unable to read config file.", details={"path": str(path), "error": str(e)}) from e

    if not raw.strip():
        return {}

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise InvalidInputError(
            "Config file is not valid JSON.",
            details={"path": str(path), "line": e.lineno, "col": e.colno},
        ) from e

    if not isinstance(data, dict):
        raise InvalidInputError(
            "Config root must be a JSON object.",
            details={"path": str(path), "type": type(data).__name__},
        )

    return data


def _write_json_file(path: Path, data: Mapping[str, Any]) -> None:
    try:
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as e:
        raise ExternalFailureError("Unable to write config file.", details={"path": str(path), "error": str(e)}) from e


def _get_mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    return None


def _extract_telegram_config(root: Mapping[str, Any]) -> Mapping[str, Any]:
    """Best-effort extraction for telegram config from a config root."""

    # Common layouts
    candidates = [
        ("channels", "telegram"),
        ("integrations", "telegram"),
        ("telegram",),
    ]

    for path in candidates:
        cur: Any = root
        ok = True
        for key in path:
            m = _get_mapping(cur)
            if m is None or key not in m:
                ok = False
                break
            cur = m[key]
        if ok and isinstance(cur, Mapping):
            return cur

    # Direct/flat layout
    if any(k in root for k in ("token", "bot_token", "chat_id")):
        return root

    return {}


def _normalize_telegram(cfg: Mapping[str, Any], env: Mapping[str, str]) -> dict[str, str]:
    token = cfg.get("token") or cfg.get("bot_token") or env.get("THOMAS_TELEGRAM_BOT_TOKEN")
    chat_id = cfg.get("chat_id") or env.get("THOMAS_TELEGRAM_CHAT_ID")

    missing: list[str] = []
    if not isinstance(token, str) or not token.strip():
        missing.append("token")
    if not isinstance(chat_id, (str, int)) or str(chat_id).strip() == "":
        missing.append("chat_id")

    if missing:
        raise MissingConfigError(
            "Missing required Telegram configuration.",
            details={
                "missing": missing,
                "expected_env": ["THOMAS_TELEGRAM_BOT_TOKEN", "THOMAS_TELEGRAM_CHAT_ID"],
            },
        )

    return {"token": token.strip(), "chat_id": str(chat_id).strip()}


def _persist_enablement(root: dict[str, Any], provider: str) -> list[str]:
    existing = root.get("channels_enabled")
    if existing is None:
        existing_list: list[str] = []
    elif isinstance(existing, list) and all(isinstance(x, str) for x in existing):
        existing_list = list(existing)
    else:
        raise InvalidInputError(
            "channels_enabled must be a list of strings when present.",
            details={"field": "channels_enabled"},
        )

    if provider not in existing_list:
        existing_list.append(provider)

    root["channels_enabled"] = existing_list
    return existing_list


# -----------------------------
# Provider integration adapters
# -----------------------------


class _TelegramIntegrationSender:
    def __init__(self) -> None:
        try:
            from thomas.integrations import telegram as telegram_mod  # type: ignore
        except (ImportError, AttributeError, RuntimeError) as e:
            raise ExternalFailureError(
                "Telegram integration module is not available.",
                details={"import": "thomas.integrations.telegram", "error": repr(e)},
            ) from e
        self._mod = telegram_mod
        self._send = getattr(telegram_mod, "send_message", None)

    def send_message(self, *, token: str, chat_id: str, text: str) -> Mapping[str, Any]:
        # Prefer module-level send_message with keyword args.
        if callable(self._send):
            try:
                return self._send(token=token, chat_id=chat_id, text=text)
            except TypeError:
                return self._send(token, chat_id, text)

        # Try a few common client class names.
        for cls_name in ("TelegramClient", "TelegramIntegration", "TelegramBot"):
            cls = getattr(self._mod, cls_name, None)
            if cls is None:
                continue
            try:
                client = cls(token)
            except TypeError:
                client = cls(token=token)

            for method_name in ("send_message", "send", "post_message"):
                method = getattr(client, method_name, None)
                if not callable(method):
                    continue
                try:
                    return method(chat_id=chat_id, text=text)
                except TypeError:
                    return method(chat_id, text)

        raise ExternalFailureError(
            "Telegram integration does not expose a supported send API.",
            details={"module": getattr(self._mod, "__name__", repr(self._mod))},
        )


def _extract_message_id(resp: Mapping[str, Any] | None) -> str | None:
    if not resp:
        return None
    if resp.get("message_id") is not None:
        return str(resp["message_id"])
    result = resp.get("result")
    if isinstance(result, Mapping) and result.get("message_id") is not None:
        return str(result["message_id"])
    return None


# -----------------------------
# Public API
# -----------------------------


def integrate_channel(
    req: ChannelIntegrationRequest,
    *,
    env: Mapping[str, str] | None = None,
    telegram_sender: TelegramSender | None = None,
) -> ChannelIntegrationResult:
    """Integrate/validate a channel provider for Thomas.

    This function is Thomas-native and intentionally small. It validates provider
    configuration, optionally persists provider enablement into the JSON config
    file, and can optionally perform an external validation step via the provider
    integration module.

    External calls are only performed when:
    - req.test_message is provided, OR
    - req.validate_external is True
    and req.dry_run is False.
    """

    provider = (req.provider or "").strip().lower()
    if not provider:
        raise InvalidInputError("provider is required.", details={"field": "provider"})

    if provider not in _SUPPORTED_PROVIDERS:
        raise InvalidInputError(
            "Unsupported provider.",
            details={"provider": provider, "supported": list(_SUPPORTED_PROVIDERS)},
        )

    if req.config is None and req.config_path is None:
        raise MissingConfigError("Either config or config_path must be provided.")

    env_map = dict(env or {})

    config_path_str: str | None = None
    wrote_config = False
    root: dict[str, Any]

    if req.config is not None:
        if not isinstance(req.config, Mapping):
            raise InvalidInputError("config must be a mapping.", details={"type": type(req.config).__name__})
        root = dict(req.config)
    else:
        assert req.config_path is not None
        config_path_str = str(req.config_path)
        root = _read_json_file(req.config_path)

    details: dict[str, Any] = {}
    warnings: list[str] = []

    enabled_channels: list[str] = []

    if provider == "telegram":
        cfg = _extract_telegram_config(root)
        normalized = _normalize_telegram(cfg, env_map)
        details["telegram"] = {"chat_id": normalized["chat_id"]}
    else:  # pragma: no cover
        normalized = {}

    # Persist enablement if requested and we have a file path.
    if req.persist_enablement and req.config_path is not None:
        enabled_channels = _persist_enablement(root, provider)
        if not req.dry_run:
            _write_json_file(req.config_path, root)
            wrote_config = True

    validated = True

    # Optional external validation / test message
    if not req.dry_run and (req.test_message is not None or req.validate_external):
        if provider == "telegram":
            sender = telegram_sender or _TelegramIntegrationSender()
            text = req.test_message or "Thomas channel validation"
            try:
                resp = sender.send_message(
                    token=normalized["token"],
                    chat_id=normalized["chat_id"],
                    text=text,
                )
            except ChannelIntegrationError:
                raise
            except (ConnectionError, TimeoutError, RuntimeError) as e:  # pragma: no cover
                raise ExternalFailureError(
                    "Provider call failed.",
                    details={"provider": provider, "error": repr(e)},
                ) from e

            msg_id = _extract_message_id(resp)
            if msg_id is not None:
                details.setdefault("telegram", {})["message_id"] = msg_id
        else:  # pragma: no cover
            warnings.append("External validation not implemented for provider.")

    return ChannelIntegrationResult(
        provider=provider,
        integrated=True,
        validated=validated,
        wrote_config=wrote_config,
        config_path=config_path_str,
        enabled_channels=enabled_channels,
        details=details,
        warnings=warnings,
    )
