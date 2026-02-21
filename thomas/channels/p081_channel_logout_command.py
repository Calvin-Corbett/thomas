from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import importlib
import importlib.util
import inspect
import json
import os
import shutil
import tempfile
from typing import Any, List, Literal, Sequence, Tuple, TypedDict, Union


class ChannelLogoutError(RuntimeError):
    """Deterministic failure for channel logout operations."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class ChannelLogoutRequest:
    """Input contract for logging out of a messaging channel.

    Notes:
    - This is a local-only cleanup. It deletes Thomas' saved auth/session artifacts
      for the channel (files/dirs + channel entries in channels.json where applicable).

    Attributes:
        channel: Channel identifier (e.g. "telegram").
        config_root: Override for the Thomas config directory.
        dry_run: When true, report what would be removed without changing anything.
        call_integration_hooks: When true, run integration cleanup hooks (best-effort).
        include_integration_hints: When true, use integration module hints to locate state files.
    """

    channel: str
    config_root: Path | None = None
    dry_run: bool = False
    call_integration_hooks: bool = False
    include_integration_hints: bool = True


@dataclass(frozen=True)
class ChannelLogoutResult:
    """Output contract for a successful logout."""
    channel: str
    removed: Tuple[str, ...]
    dry_run: bool = False


class LogoutSuccessJson(TypedDict):
    ok: Literal[True]
    channel: str
    removed: List[str]
    dry_run: bool


class LogoutErrorJson(TypedDict):
    code: str
    message: str


class LogoutFailureJson(TypedDict):
    ok: Literal[False]
    error: LogoutErrorJson


LogoutJson = Union[LogoutSuccessJson, LogoutFailureJson]


_ALIAS_MAP: dict[str, str] = {
    "tg": "telegram",
}


def logout_channel(request: ChannelLogoutRequest) -> ChannelLogoutResult:
    """Log out of a configured channel by removing locally stored auth/session state."""
    channel_raw = (request.channel or "").strip().lower()
    if not channel_raw:
        raise ChannelLogoutError("invalid_input", "Channel name is required.")

    channel = _ALIAS_MAP.get(channel_raw, channel_raw)

    config_root = _resolve_config_root(request.config_root)

    if not config_root.exists():
        raise ChannelLogoutError(
            "missing_config",
            f"Thomas config directory does not exist: {config_root}",
        )

    targets = _discover_logout_targets(
        config_root,
        channel,
        include_integration_hints=request.include_integration_hints,
    )

    if not targets:
        if not _integration_available(channel):
            raise ChannelLogoutError("unknown_channel", f"Unknown channel '{channel_raw}'.")
        raise ChannelLogoutError(
            "not_logged_in",
            f"No saved auth state found for channel '{channel}'.",
        )

    removed: list[str] = []
    for target in targets:
        if isinstance(target, _JsonChannelKeyTarget):
            if request.dry_run:
                removed.append(str(target.path))
                continue
            changed = _remove_channel_from_json(target.path, channel)
            if changed:
                removed.append(str(target.path))
            continue

        path = target
        if request.dry_run:
            removed.append(str(path))
            continue
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            removed.append(str(path))
        except FileNotFoundError:
            continue
        except Exception as e:  # pragma: no cover
            raise ChannelLogoutError("external_failure", f"Failed to remove '{path}': {e}") from e

    if request.call_integration_hooks and not request.dry_run:
        _call_integration_logout_hook(channel, config_root)

    return ChannelLogoutResult(
        channel=channel,
        removed=tuple(sorted(set(removed))),
        dry_run=request.dry_run,
    )


def logout_result_to_json(result: ChannelLogoutResult) -> LogoutSuccessJson:
    return {
        "ok": True,
        "channel": result.channel,
        "removed": list(result.removed),
        "dry_run": bool(result.dry_run),
    }


def error_to_json(error: ChannelLogoutError) -> LogoutFailureJson:
    return {"ok": False, "error": {"code": error.code, "message": error.message}}


def _resolve_config_root(config_root: Path | None) -> Path:
    if config_root is not None:
        return Path(config_root).expanduser()

    env = os.getenv("THOMAS_CONFIG_DIR") or os.getenv("THOMAS_HOME")
    if env:
        return Path(env).expanduser()

    xdg = os.getenv("XDG_CONFIG_HOME")
    if xdg:
        return (Path(xdg).expanduser() / "thomas")

    return Path.home() / ".thomas"


def _integration_available(channel: str) -> bool:
    # Telegram is expected to exist in the standard Thomas distro.
    if channel == "telegram":
        return True
    try:
        return importlib.util.find_spec(f"thomas.integrations.{channel}") is not None
    except ModuleNotFoundError:
        return False


@dataclass(frozen=True)
class _JsonChannelKeyTarget:
    path: Path


def _discover_logout_targets(
    config_root: Path,
    channel: str,
    *,
    include_integration_hints: bool,
) -> list[Path | _JsonChannelKeyTarget]:
    candidates: list[Path | _JsonChannelKeyTarget] = []

    # Common file and folder conventions.
    candidates.extend(
        [
            config_root / "channels" / channel,
            config_root / "channels" / f"{channel}.json",
            config_root / "channels" / f"{channel}.toml",
            config_root / "channels" / f"{channel}.yaml",
            config_root / "channels" / f"{channel}.yml",
            config_root / "integrations" / channel,
            config_root / "integrations" / f"{channel}.json",
            config_root / "integrations" / f"{channel}.toml",
            config_root / "integrations" / f"{channel}.yaml",
            config_root / "integrations" / f"{channel}.yml",
            config_root / f"{channel}.json",
            config_root / f"{channel}.toml",
            config_root / f"{channel}.yaml",
            config_root / f"{channel}.yml",
            config_root / f"{channel}.session",
            config_root / f"{channel}.session-journal",
        ]
    )

    # Known telegram-ish session patterns (telethon, etc.).
    if channel == "telegram":
        candidates.extend(
            [
                config_root / "telegram.session",
                config_root / "telegram.session-journal",
                config_root / "telegram",
                config_root / "integrations" / "telegram.session",
            ]
        )

    # channels.json may contain a key for the channel; treat it as an editable target.
    channels_json = config_root / "channels.json"
    if channels_json.exists() and _json_contains_channel(channels_json, channel):
        candidates.append(_JsonChannelKeyTarget(path=channels_json))

    # Integration hints are optional and best-effort.
    if include_integration_hints and _integration_available(channel):
        candidates.extend(_integration_hint_paths(channel, config_root))

    filtered: list[Path | _JsonChannelKeyTarget] = []
    for c in candidates:
        if isinstance(c, _JsonChannelKeyTarget):
            filtered.append(c)
            continue
        if c.exists():
            filtered.append(c)

    # Deduplicate.
    seen: set[str] = set()
    out: list[Path | _JsonChannelKeyTarget] = []
    for item in filtered:
        key = str(item.path) if isinstance(item, _JsonChannelKeyTarget) else str(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _json_contains_channel(path: Path, channel: str) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False

    if isinstance(data, dict):
        if channel in data:
            return True
        nested = data.get("channels")
        if isinstance(nested, dict) and channel in nested:
            return True
    return False


def _remove_channel_from_json(path: Path, channel: str) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise ChannelLogoutError("external_failure", f"Failed to parse JSON config '{path}': {e}") from e

    if not isinstance(data, dict):
        raise ChannelLogoutError(
            "external_failure",
            f"Expected JSON object in {path}, got {type(data).__name__}.",
        )

    changed = False
    if channel in data:
        data.pop(channel, None)
        changed = True

    nested = data.get("channels")
    if isinstance(nested, dict) and channel in nested:
        nested.pop(channel, None)
        changed = True

    if not changed:
        return False

    # Atomic write: write to temp file and replace.
    tmp_dir = path.parent
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(tmp_dir)) as tf:
            tf.write(json.dumps(data, indent=2, sort_keys=True) + "\n")
            tmp_name = tf.name
        os.replace(tmp_name, str(path))
    except Exception as e:
        # Best-effort cleanup.
        try:
            if "tmp_name" in locals() and os.path.exists(tmp_name):
                os.unlink(tmp_name)
        except Exception:
            pass
        raise ChannelLogoutError("external_failure", f"Failed to write JSON config '{path}': {e}") from e

    return True


def _integration_hint_paths(channel: str, config_root: Path) -> list[Path]:
    """Best-effort discovery of state paths exposed by an integration module."""
    module_name = f"thomas.integrations.{channel}"
    try:
        mod = importlib.import_module(module_name)
    except ModuleNotFoundError:
        return []
    except Exception:
        # Hints are optional; don't fail logout due to heavy integration deps.
        return []

    hint_paths: list[Path] = []

    for fn_name in (
        "config_path",
        "get_config_path",
        "state_path",
        "get_state_path",
        "session_path",
        "get_session_path",
        "auth_path",
        "get_auth_path",
    ):
        fn = getattr(mod, fn_name, None)
        if callable(fn):
            hint_paths.extend(_safe_call_path_function(fn, config_root))

    # Optional constants.
    for attr_name, value in vars(mod).items():
        if not attr_name.upper().endswith(("_PATH", "_FILE", "_DIR", "_SESSION")):
            continue
        if isinstance(value, (str, Path)):
            try:
                hint_paths.append(Path(value).expanduser())
            except Exception:
                continue

    normalised: list[Path] = []
    for p in hint_paths:
        normalised.append((config_root / p) if not p.is_absolute() else p)
    return normalised


def _safe_call_path_function(fn: Any, config_root: Path) -> list[Path]:
    try:
        sig = inspect.signature(fn)
    except Exception:
        return []

    kwargs: dict[str, Any] = {}
    for name in ("config_root", "config_dir", "root", "base_dir"):
        if name in sig.parameters:
            kwargs[name] = config_root

    required_params = [
        p
        for p in sig.parameters.values()
        if p.default is inspect.Signature.empty
        and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
    ]
    if required_params and not kwargs:
        return []

    try:
        value = fn(**kwargs) if kwargs else fn()
    except Exception:
        return []

    if value is None:
        return []
    if isinstance(value, (str, Path)):
        return [Path(value)]
    if isinstance(value, Sequence):
        out: list[Path] = []
        for item in value:
            if isinstance(item, (str, Path)):
                out.append(Path(item))
        return out
    return []


def _call_integration_logout_hook(channel: str, config_root: Path) -> None:
    module_name = f"thomas.integrations.{channel}"
    try:
        mod = importlib.import_module(module_name)
    except ModuleNotFoundError:
        return
    except Exception as e:
        raise ChannelLogoutError("external_failure", f"Failed to load integration '{channel}': {e}") from e

    for fn_name in ("logout", "clear_auth", "clear_credentials", "sign_out"):
        fn = getattr(mod, fn_name, None)
        if callable(fn):
            _safe_call_logout_hook(fn, config_root)
            return


def _safe_call_logout_hook(fn: Any, config_root: Path) -> None:
    try:
        sig = inspect.signature(fn)
    except Exception:
        return

    kwargs: dict[str, Any] = {}
    for name in ("config_root", "config_dir", "root", "base_dir"):
        if name in sig.parameters:
            kwargs[name] = config_root

    required_params = [
        p
        for p in sig.parameters.values()
        if p.default is inspect.Signature.empty
        and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
    ]
    if required_params and not kwargs:
        return

    try:
        fn(**kwargs) if kwargs else fn()
    except Exception as e:
        raise ChannelLogoutError("external_failure", f"Integration logout hook failed: {e}") from e
