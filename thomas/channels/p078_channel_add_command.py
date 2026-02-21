"""thomas.channels.p078_channel_add_command

P078 — Channel add command (Thomas-native)

Adds a channel account entry to Thomas' config file in a deterministic, testable way.

Philosophy:
- Core logic is pure-ish and file-path explicit: no hidden globals.
- CLI is a thin wrapper: parse flags, resolve config path, call core.
- Errors are deterministic via stable error codes (automation-friendly).
- Writes are atomic (tempfile + os.replace).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Callable
import importlib
import json
import os
import tempfile


# -----------------------------
# Contracts
# -----------------------------


@dataclass(frozen=True)
class ChannelAddRequest:
    """Input contract for adding a channel account."""

    channel: str
    token: str
    account: str = "default"
    name: Optional[str] = None
    config_path: Optional[Path] = None
    overwrite: bool = False
    verify: bool = False  # optional external validation (best-effort)


@dataclass(frozen=True)
class ChannelAddResult:
    """Output contract for a successful channel add."""

    channel: str
    account: str
    config_path: Path
    name: Optional[str] = None

    created_channel: bool = False
    created_account: bool = False
    overwritten: bool = False

    verified: bool = False
    verification_subject: Optional[str] = None  # e.g. bot username

    written_keys: list[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["config_path"] = str(self.config_path)
        return d


# -----------------------------
# Deterministic errors
# -----------------------------


class ChannelAddError(Exception):
    """Base class for deterministic errors raised by this command."""

    def __init__(
        self, *, code: str, message: str, details: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class ChannelAddValidationError(ChannelAddError):
    pass


class ChannelAddConfigError(ChannelAddError):
    pass


class ChannelAddExternalError(ChannelAddError):
    pass


# -----------------------------
# Public API
# -----------------------------


def add_channel(request: ChannelAddRequest) -> ChannelAddResult:
    """Add a channel account to config.

    Raises:
      - ChannelAddValidationError: invalid user input.
      - ChannelAddConfigError: config missing/unreadable/invalid shape.
      - ChannelAddExternalError: write failures or external verification failures.
    """
    channel = _normalize_key(request.channel, what="channel")
    account = _normalize_key(request.account or "default", what="account")
    token = (request.token or "").strip()

    if not token:
        raise ChannelAddValidationError(
            code="invalid_input",
            message="Missing required token.",
            details={"field": "token"},
        )

    config_path = request.config_path
    if config_path is None:
        raise ChannelAddConfigError(
            code="config_path_missing",
            message="No config path provided to channel add operation.",
        )
    config_path = Path(config_path)

    if not config_path.exists():
        raise ChannelAddConfigError(
            code="config_missing",
            message=f"Config file not found: {config_path}",
            details={"config_path": str(config_path)},
        )

    config = _read_config(config_path)

    updated, base_result = apply_channel_add(
        config,
        request=ChannelAddRequest(
            channel=channel,
            token=token,
            account=account,
            name=request.name,
            config_path=config_path,
            overwrite=request.overwrite,
            verify=request.verify,
        ),
    )

    verified = False
    subject: Optional[str] = None
    if request.verify:
        verified, subject = _verify_credentials(channel=channel, token=token)

    _write_config_atomic(config_path, updated)

    return ChannelAddResult(
        channel=base_result.channel,
        account=base_result.account,
        config_path=config_path,
        name=base_result.name,
        created_channel=base_result.created_channel,
        created_account=base_result.created_account,
        overwritten=base_result.overwritten,
        verified=verified,
        verification_subject=subject,
        written_keys=base_result.written_keys,
    )


def apply_channel_add(
    config: Dict[str, Any], *, request: ChannelAddRequest
) -> Tuple[Dict[str, Any], ChannelAddResult]:
    """Pure-ish transformer: applies the add to an in-memory config dict."""
    channel = _normalize_key(request.channel, what="channel")
    account = _normalize_key(request.account or "default", what="account")
    token = (request.token or "").strip()
    if not token:
        raise ChannelAddValidationError(
            code="invalid_input",
            message="Missing required token.",
            details={"field": "token"},
        )

    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise ChannelAddConfigError(
            code="config_invalid",
            message="Config root must be an object.",
            details={"found_type": type(config).__name__},
        )

    channels = config.get("channels")
    if channels is None:
        channels = {}
        config["channels"] = channels
    if not isinstance(channels, dict):
        raise ChannelAddConfigError(
            code="config_invalid",
            message="Config field 'channels' must be an object.",
            details={"found_type": type(channels).__name__},
        )

    created_channel = False
    chan_cfg = channels.get(channel)
    if chan_cfg is None:
        chan_cfg = {}
        channels[channel] = chan_cfg
        created_channel = True
    if not isinstance(chan_cfg, dict):
        raise ChannelAddConfigError(
            code="config_invalid",
            message=f"Config field 'channels.{channel}' must be an object.",
            details={"found_type": type(chan_cfg).__name__},
        )

    accounts = chan_cfg.get("accounts")
    if accounts is None:
        accounts = {}
        chan_cfg["accounts"] = accounts
    if not isinstance(accounts, dict):
        raise ChannelAddConfigError(
            code="config_invalid",
            message=f"Config field 'channels.{channel}.accounts' must be an object.",
            details={"found_type": type(accounts).__name__},
        )

    existing = accounts.get(account)
    overwritten = False
    if existing is not None and not request.overwrite:
        raise ChannelAddConfigError(
            code="account_exists",
            message=f"Account '{account}' already exists for channel '{channel}'.",
            details={"channel": channel, "account": account},
        )
    if existing is not None:
        overwritten = True

    created_account = existing is None
    entry: Dict[str, Any] = dict(existing) if isinstance(existing, dict) else {}

    entry["enabled"] = True
    if request.name is not None:
        entry["name"] = request.name

    token_key, also_set_channel_level = _token_field_for_channel(channel)
    entry[token_key] = token

    if also_set_channel_level and account == "default":
        chan_cfg[token_key] = token

    chan_cfg["enabled"] = True
    accounts[account] = entry

    written_keys = ["channels", channel, "accounts", account, token_key]

    result = ChannelAddResult(
        channel=channel,
        account=account,
        name=request.name,
        config_path=Path(request.config_path) if request.config_path else Path("<unknown>"),
        created_channel=created_channel,
        created_account=created_account,
        overwritten=overwritten,
        verified=False,
        verification_subject=None,
        written_keys=written_keys,
    )
    return config, result


# -----------------------------
# Helpers
# -----------------------------


def _normalize_key(value: str, *, what: str) -> str:
    v = (value or "").strip().lower()
    if not v:
        raise ChannelAddValidationError(
            code="invalid_input",
            message=f"Missing required {what}.",
            details={"field": what},
        )
    for ch in v:
        if not (ch.isalnum() or ch in ("-", "_")):
            raise ChannelAddValidationError(
                code="invalid_input",
                message=(
                    f"Invalid {what} '{value}'. Only letters, digits, '-' and '_' are allowed."
                ),
                details={"field": what, "value": value},
            )
    return v


def _token_field_for_channel(channel: str) -> Tuple[str, bool]:
    """Return (token_field_name, also_set_channel_level_for_default_account)."""
    if channel == "telegram":
        return "bot_token", True
    return "token", False


def _read_config(path: Path) -> Dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ChannelAddConfigError(
            code="config_unreadable",
            message=f"Unable to read config file: {path}",
            details={"config_path": str(path), "error": str(e)},
        ) from e

    raw = raw.strip()
    if not raw:
        return {}

    loader = _json_loader()
    try:
        data = loader(raw)
    except Exception as e:
        raise ChannelAddConfigError(
            code="config_invalid",
            message="Config file is not valid JSON/JSON5.",
            details={"config_path": str(path), "error": str(e)},
        ) from e

    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ChannelAddConfigError(
            code="config_invalid",
            message="Config root must be a JSON object.",
            details={"config_path": str(path), "found_type": type(data).__name__},
        )
    return data


def _json_loader() -> Callable[[str], Any]:
    """Prefer JSON5 on read if installed; fall back to stdlib JSON."""
    try:  # pragma: no cover
        import json5  # type: ignore

        return json5.loads  # type: ignore[attr-defined]
    except Exception:
        return json.loads


def _write_config_atomic(path: Path, data: Dict[str, Any]) -> None:
    payload = json.dumps(data, indent=2) + "\n"
    tmp_path: Optional[Path] = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(path.parent),
            delete=False,
            prefix=path.name + ".",
            suffix=".tmp",
        ) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(payload)
            tmp.flush()
            try:
                os.fsync(tmp.fileno())
            except Exception:
                pass
        os.replace(str(tmp_path), str(path))
    except OSError as e:
        raise ChannelAddExternalError(
            code="config_write_failed",
            message="Failed to write updated configuration.",
            details={"config_path": str(path), "error": str(e)},
        ) from e
    finally:
        try:
            if tmp_path is not None and tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


def _verify_credentials(*, channel: str, token: str) -> Tuple[bool, Optional[str]]:
    """Optional, best-effort credential verification.

    If verification is requested and fails, raise a deterministic error.
    """
    if channel == "telegram":
        info = _verify_telegram_bot_token(token)
        username = None
        if isinstance(info, dict):
            username = info.get("username") or info.get("user_name") or info.get("bot_username")
        return True, username
    return True, None


def _verify_telegram_bot_token(token: str) -> Dict[str, Any]:
    """Verify a Telegram bot token.

    First tries Thomas' own telegram integration module if it exposes a helper.
    Falls back to a direct HTTPS call (requests) only if needed.
    """
    try:
        mod = importlib.import_module("thomas.integrations.telegram")
        for name in (
            "get_bot_info",
            "get_me",
            "telegram_get_me",
            "validate_bot_token",
            "bot_get_me",
        ):
            fn = getattr(mod, name, None)
            if callable(fn):
                try:
                    out = fn(token)  # type: ignore[misc]
                    return out if isinstance(out, dict) else {"result": out}
                except ChannelAddError:
                    raise
                except Exception as e:
                    raise ChannelAddExternalError(
                        code="telegram_token_invalid",
                        message="Telegram token verification failed.",
                        details={"error": str(e)},
                    ) from e
    except ModuleNotFoundError:
        pass
    except Exception:
        pass

    try:
        import requests  # type: ignore
    except Exception as e:
        raise ChannelAddExternalError(
            code="telegram_verify_unavailable",
            message=(
                "Cannot verify Telegram token (missing dependency 'requests' and no integration helper found)."
            ),
            details={"error": str(e)},
        ) from e

    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        resp = requests.get(url, timeout=5)
    except Exception as e:
        raise ChannelAddExternalError(
            code="telegram_unreachable",
            message="Failed to reach Telegram Bot API while verifying token.",
            details={"error": str(e)},
        ) from e

    try:
        payload = resp.json()
    except Exception:
        payload = {"ok": False, "error": resp.text}

    if resp.status_code != 200 or not isinstance(payload, dict) or not payload.get("ok"):
        raise ChannelAddExternalError(
            code="telegram_token_invalid",
            message="Telegram token verification failed.",
            details={"status_code": resp.status_code, "response": payload},
        )

    result = payload.get("result")
    return result if isinstance(result, dict) else {}
