"""
P079 - Channel remove command (Thomas-native)

Implements the core, non-CLI business logic for disabling or deleting a
configured messaging channel (or per-channel account) from Thomas config.

Design goals:
- Deterministic, machine-readable errors (ChannelRemoveError with codes).
- Clear input/output contracts (dataclasses).
- Minimal assumptions about the surrounding Thomas codebase; callers may
  inject config loaders/writers for testability.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class ChannelRemoveErrorCode(str, Enum):
    INVALID_INPUT = "INVALID_INPUT"
    CONFIG_NOT_FOUND = "CONFIG_NOT_FOUND"
    CONFIG_INVALID = "CONFIG_INVALID"
    CHANNEL_NOT_FOUND = "CHANNEL_NOT_FOUND"
    ACCOUNT_NOT_FOUND = "ACCOUNT_NOT_FOUND"
    WRITE_FAILED = "WRITE_FAILED"
    EXTERNAL_FAILURE = "EXTERNAL_FAILURE"


@dataclass(frozen=True)
class ChannelRemoveRequest:
    """Input contract for channel removal."""

    channel: str
    account: str | None = None
    delete: bool = False
    # Optional explicit config path. If omitted, config discovery is used.
    config_path: Path | None = None


@dataclass(frozen=True)
class ChannelRemoveResult:
    """Output contract for channel removal."""

    channel: str
    account: str
    action: str  # "disabled" or "deleted"
    changed: bool
    config_path: Path

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


class ChannelRemoveError(RuntimeError):
    """Deterministic error with a stable code."""

    def __init__(self, code: ChannelRemoveErrorCode, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})

    @property
    def exit_code(self) -> int:
        # Stable exit codes for automation.
        return {
            ChannelRemoveErrorCode.INVALID_INPUT: 2,
            ChannelRemoveErrorCode.CONFIG_NOT_FOUND: 3,
            ChannelRemoveErrorCode.CONFIG_INVALID: 4,
            ChannelRemoveErrorCode.CHANNEL_NOT_FOUND: 5,
            ChannelRemoveErrorCode.ACCOUNT_NOT_FOUND: 6,
            ChannelRemoveErrorCode.WRITE_FAILED: 7,
            ChannelRemoveErrorCode.EXTERNAL_FAILURE: 8,
        }.get(self.code, 1)

    def to_json_dict(self) -> dict[str, Any]:
        return {"code": self.code.value, "message": str(self), "details": self.details}


_YAML_SUFFIXES = {".yaml", ".yml"}


def discover_config_path() -> Path:
    """
    Best-effort config discovery.

    Order:
      1) THOMAS_CONFIG_PATH / THOMAS_CONFIG_FILE / THOMAS_CONFIG
      2) THOMAS_HOME + (thomas.json|config.json)
      3) XDG_CONFIG_HOME/thomas/(config.json|thomas.json)
      4) ~/.config/thomas/(config.json|thomas.json)
      5) ~/.thomas/(config.json|thomas.json)

    Returns a Path even if the file does not exist; callers decide how to handle.
    """
    env_candidates = [
        os.environ.get("THOMAS_CONFIG_PATH"),
        os.environ.get("THOMAS_CONFIG_FILE"),
        os.environ.get("THOMAS_CONFIG"),
    ]
    for raw in env_candidates:
        if raw:
            return Path(raw).expanduser()

    thomas_home = os.environ.get("THOMAS_HOME")
    if thomas_home:
        home = Path(thomas_home).expanduser()
        for name in ("thomas.json", "config.json"):
            p = home / name
            if p.exists():
                return p
        return home / "thomas.json"

    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        base = Path(xdg).expanduser() / "thomas"
        for name in ("config.json", "thomas.json"):
            p = base / name
            if p.exists():
                return p
        return base / "config.json"

    for base in (Path.home() / ".config" / "thomas", Path.home() / ".thomas"):
        for name in ("config.json", "thomas.json"):
            p = base / name
            if p.exists():
                return p
    return Path.home() / ".thomas" / "config.json"


def _load_yaml(text: str) -> Any:
    try:
        import yaml  # type: ignore
    except (json.JSONDecodeError, ValueError, KeyError) as e:  # pragma: no cover
        raise ChannelRemoveError(
            ChannelRemoveErrorCode.CONFIG_INVALID,
            "Config appears to be YAML but PyYAML is not available.",
            details={"error": str(e)},
        )
    try:
        return yaml.safe_load(text)
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        raise ChannelRemoveError(
            ChannelRemoveErrorCode.CONFIG_INVALID,
            "Failed to parse YAML config.",
            details={"error": str(e)},
        )


def _dump_yaml(data: Any) -> str:
    try:
        import yaml  # type: ignore
    except (json.JSONDecodeError, ValueError, KeyError) as e:  # pragma: no cover
        raise ChannelRemoveError(
            ChannelRemoveErrorCode.WRITE_FAILED,
            "Config target is YAML but PyYAML is not available.",
            details={"error": str(e)},
        )
    try:
        return yaml.safe_dump(data, sort_keys=False)
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        raise ChannelRemoveError(
            ChannelRemoveErrorCode.WRITE_FAILED,
            "Failed to serialize YAML config.",
            details={"error": str(e)},
        )


def load_config_file(path: Path) -> MutableMapping[str, Any]:
    if not path.exists():
        raise ChannelRemoveError(
            ChannelRemoveErrorCode.CONFIG_NOT_FOUND,
            f"Config file not found: {path}",
            details={"path": str(path)},
        )
    try:
        text = path.read_text(encoding="utf-8")
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        raise ChannelRemoveError(
            ChannelRemoveErrorCode.CONFIG_INVALID,
            f"Failed to read config file: {path}",
            details={"path": str(path), "error": str(e)},
        )

    if not text.strip():
        return {}

    if path.suffix.lower() in _YAML_SUFFIXES:
        data = _load_yaml(text)
    else:
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            raise ChannelRemoveError(
                ChannelRemoveErrorCode.CONFIG_INVALID,
                "Failed to parse JSON config.",
                details={"path": str(path), "error": str(e)},
            )

    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ChannelRemoveError(
            ChannelRemoveErrorCode.CONFIG_INVALID,
            "Config root must be an object/dict.",
            details={"path": str(path), "type": type(data).__name__},
        )
    return data  # type: ignore[return-value]


def write_config_file(path: Path, cfg: Mapping[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except (KeyError, ValueError, AttributeError):
        pass

    try:
        if path.suffix.lower() in _YAML_SUFFIXES:
            payload = _dump_yaml(cfg)
        else:
            payload = json.dumps(cfg, indent=2, sort_keys=False) + "\n"
        path.write_text(payload, encoding="utf-8")
    except ChannelRemoveError:
        raise
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        raise ChannelRemoveError(
            ChannelRemoveErrorCode.WRITE_FAILED,
            f"Failed to write config file: {path}",
            details={"path": str(path), "error": str(e)},
        )


def _normalize_channel(value: str) -> str:
    v = (value or "").strip()
    if not v:
        raise ChannelRemoveError(ChannelRemoveErrorCode.INVALID_INPUT, "Channel is required.")
    if any(ch.isspace() for ch in v):
        raise ChannelRemoveError(
            ChannelRemoveErrorCode.INVALID_INPUT,
            "Channel must not contain whitespace.",
            details={"channel": value},
        )
    return v.lower()


def _normalize_account(value: str | None) -> str:
    v = (value or "").strip()
    if not v:
        return "default"
    return v


def _locate_channels_section(cfg: MutableMapping[str, Any], channel: str) -> tuple[MutableMapping[str, Any], str]:
    """
    Returns (container_dict, location_label) where container_dict holds channel keys.

    Supports both:
      - cfg["channels"][channel]
      - cfg[channel] (root) if present
    """
    channels = cfg.get("channels")
    if isinstance(channels, dict):
        return channels, "channels"
    if channel in cfg and isinstance(cfg.get(channel), dict):
        return cfg, "root"
    if "channels" in cfg and not isinstance(channels, dict):
        raise ChannelRemoveError(
            ChannelRemoveErrorCode.CONFIG_INVALID,
            "Config key 'channels' must be an object/dict.",
            details={"type": type(channels).__name__},
        )
    return {}, "missing"


def _cleanup_external_state_after_delete(channel: str, account: str) -> None:
    """
    Best-effort cleanup hook.

    Today we only attempt Telegram-specific cleanup (if present), but we keep this
    optional to avoid hard coupling with integrations.
    """
    if channel != "telegram":
        return

    try:
        from importlib import import_module

        mod = import_module("thomas.integrations.telegram")
    except (ImportError, AttributeError, RuntimeError):
        return

    candidate_fns = [
        "delete_update_offset",
        "delete_telegram_update_offset",
        "delete_polling_offset",
        "delete_polling_state",
    ]
    for name in candidate_fns:
        fn = getattr(mod, name, None)
        if not callable(fn):
            continue
        try:
            try:
                fn(account)
            except TypeError:
                fn(account_id=account)
        except FileNotFoundError:
            return
        except OSError as e:
            if getattr(e, "errno", None) == 2:
                return
            raise ChannelRemoveError(
                ChannelRemoveErrorCode.EXTERNAL_FAILURE,
                "Failed cleaning up Telegram channel state.",
                details={"function": name, "error": str(e)},
            )
        except (ImportError, AttributeError, RuntimeError) as e:
            raise ChannelRemoveError(
                ChannelRemoveErrorCode.EXTERNAL_FAILURE,
                "Failed cleaning up Telegram channel state.",
                details={"function": name, "error": str(e)},
            )
        return


def remove_channel(
    request: ChannelRemoveRequest,
    *,
    cfg: MutableMapping[str, Any] | None = None,
    load_cfg: Callable[[Path], MutableMapping[str, Any]] | None = None,
    write_cfg: Callable[[Path, Mapping[str, Any]], None] | None = None,
) -> ChannelRemoveResult:
    """
    Disable (default) or delete (destructive) a channel from config.

    If `cfg` is not provided, config is loaded from disk using either:
      - request.config_path, or
      - discover_config_path()

    The on-disk config is updated unless callers inject a no-op writer.

    Raises:
      ChannelRemoveError with stable codes.
    """
    channel = _normalize_channel(request.channel)
    account = _normalize_account(request.account)
    config_path = request.config_path or discover_config_path()

    loader = load_cfg or load_config_file
    writer = write_cfg or write_config_file

    local_cfg = cfg if cfg is not None else loader(config_path)

    container, location = _locate_channels_section(local_cfg, channel)
    if location == "missing":
        raise ChannelRemoveError(
            ChannelRemoveErrorCode.CHANNEL_NOT_FOUND,
            f"Channel not configured: {channel}",
            details={"channel": channel},
        )

    if channel not in container:
        raise ChannelRemoveError(
            ChannelRemoveErrorCode.CHANNEL_NOT_FOUND,
            f"Channel not configured: {channel}",
            details={"channel": channel},
        )

    channel_cfg = container.get(channel)
    if not isinstance(channel_cfg, dict):
        raise ChannelRemoveError(
            ChannelRemoveErrorCode.CONFIG_INVALID,
            f"Channel config for '{channel}' must be an object/dict.",
            details={"channel": channel, "type": type(channel_cfg).__name__},
        )

    is_default_account = account in ("default", "primary")
    target_cfg: MutableMapping[str, Any]
    if is_default_account:
        target_cfg = channel_cfg
    else:
        accounts = channel_cfg.get("accounts")
        if not isinstance(accounts, dict) or account not in accounts:
            raise ChannelRemoveError(
                ChannelRemoveErrorCode.ACCOUNT_NOT_FOUND,
                f"Account not configured for channel '{channel}': {account}",
                details={"channel": channel, "account": account},
            )
        acc_cfg = accounts.get(account)
        if not isinstance(acc_cfg, dict):
            raise ChannelRemoveError(
                ChannelRemoveErrorCode.CONFIG_INVALID,
                f"Account config for '{channel}/{account}' must be an object/dict.",
                details={"channel": channel, "account": account, "type": type(acc_cfg).__name__},
            )
        target_cfg = acc_cfg  # type: ignore[assignment]

    changed = True
    action = "deleted" if request.delete else "disabled"

    if request.delete:
        if is_default_account:
            del container[channel]
        else:
            accounts = channel_cfg.get("accounts")
            assert isinstance(accounts, dict)
            del accounts[account]
            if len(accounts) == 0:
                channel_cfg.pop("accounts", None)
        _cleanup_external_state_after_delete(channel, account)
    else:
        prior = target_cfg.get("enabled")
        if prior is False:
            changed = False
        target_cfg["enabled"] = False

    # Persist result.
    writer(config_path, local_cfg)

    return ChannelRemoveResult(
        channel=channel,
        account=account,
        action=action,
        changed=changed,
        config_path=config_path,
    )
