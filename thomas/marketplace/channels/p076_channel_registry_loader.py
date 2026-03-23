"""Channel registry loading utilities.

This module is intentionally self-contained so it can be used by both CLI and
runtime code without pulling in heavy dependencies.

The registry format is designed to be human-friendly (YAML/JSON/TOML) while
remaining easy to validate and serialize.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomllib

try:  # Optional dependency
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

try:  # Prefer a project-level base error if available
    from thomas.exceptions import ThomasError as _ThomasBaseError  # type: ignore
except (ImportError, AttributeError):  # pragma: no cover
    _ThomasBaseError = Exception  # type: ignore[misc,assignment]


class ChannelRegistryError(_ThomasBaseError):
    """Base error for channel registry loading failures.

    The ``code`` field is stable and intended for automation.
    """

    code: str

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details: dict[str, Any] = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self), "details": dict(self.details)}


class ChannelRegistryNotFoundError(ChannelRegistryError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__("channel_registry_not_found", message, details=details)


class ChannelRegistryIOError(ChannelRegistryError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__("channel_registry_io_error", message, details=details)


class ChannelRegistryParseError(ChannelRegistryError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__("channel_registry_parse_error", message, details=details)


class ChannelRegistryValidationError(ChannelRegistryError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__("channel_registry_validation_error", message, details=details)


class ChannelRegistryUnsupportedFormatError(ChannelRegistryError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__("channel_registry_unsupported_format", message, details=details)


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ChannelRegistryLoadRequest:
    """Input contract for :func:`load_channel_registry`."""

    registry_path: str | Path | None = None
    """Optional explicit path to a registry file.

    When omitted, :func:`load_channel_registry` will look at environment
    variables and a small set of default filenames.
    """

    env: Mapping[str, str] | None = None
    """Environment override (primarily for tests). Defaults to ``os.environ``."""

    strict: bool = True
    """When ``True``, applies best-effort validation for known channel kinds."""


@dataclass(frozen=True, slots=True)
class ChannelDefinition:
    """A normalized channel definition."""

    name: str
    kind: str
    config: Mapping[str, Any]
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "enabled": self.enabled,
            "config": dict(self.config),
        }


@dataclass(frozen=True, slots=True)
class ChannelRegistryLoadResult:
    """Output contract for :func:`load_channel_registry`."""

    source_path: str
    channels: Sequence[ChannelDefinition]

    def to_dict(self) -> dict[str, Any]:
        return {"source_path": self.source_path, "channels": [c.to_dict() for c in self.channels]}


# ---------------------------------------------------------------------------
# Schema helpers (for automation)
# ---------------------------------------------------------------------------


def channel_registry_load_result_schema() -> dict[str, Any]:
    """Return a small JSON schema for the CLI ``--json`` output."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Thomas Channel Registry Load Output",
        "type": "object",
        "properties": {
            "ok": {"type": "boolean"},
            "registry": {
                "type": "object",
                "properties": {
                    "source_path": {"type": "string"},
                    "channels": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "kind": {"type": "string"},
                                "enabled": {"type": "boolean"},
                                "config": {"type": "object"},
                            },
                            "required": ["name", "kind", "enabled", "config"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["source_path", "channels"],
                "additionalProperties": False,
            },
            "error": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "message": {"type": "string"},
                    "details": {"type": "object"},
                },
                "required": ["code", "message", "details"],
                "additionalProperties": False,
            },
        },
        "required": ["ok"],
        "additionalProperties": False,
    }


# ---------------------------------------------------------------------------
# Loader implementation
# ---------------------------------------------------------------------------

_ENV_VAR_KEYS: tuple[str, ...] = (
    "THOMAS_CHANNEL_REGISTRY",
    "THOMAS_CHANNELS_FILE",
    "THOMAS_CHANNELS",
)

_DEFAULT_FILENAMES: tuple[str, ...] = (
    "thomas.marketplace.channels.yaml",
    "thomas.marketplace.channels.yml",
    "thomas.marketplace.channels.json",
    "thomas.marketplace.channels.toml",
    "channels.yaml",
    "channels.yml",
    "channels.json",
    "channels.toml",
)

# Supports ${VAR} and ${VAR:-default}
_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")


def load_channel_registry(request: ChannelRegistryLoadRequest) -> ChannelRegistryLoadResult:
    """Load and validate a channel registry.

    Supported registry file formats:
    - YAML (.yaml/.yml) (requires PyYAML)
    - JSON (.json)
    - TOML (.toml)

    Env substitution supports ${VAR} and ${VAR:-default}.
    """
    env = dict(os.environ if request.env is None else request.env)

    path = _resolve_registry_path(request.registry_path, env)
    raw_text = _read_text_file(path)
    parsed = _parse_registry(raw_text, path)
    channels_raw = _extract_channels(parsed)
    channels = _normalize_channels(channels_raw, env=env, strict=request.strict)
    return ChannelRegistryLoadResult(source_path=str(path), channels=channels)


def _resolve_registry_path(registry_path: str | Path | None, env: Mapping[str, str]) -> Path:
    if registry_path is not None:
        if isinstance(registry_path, Path):
            path = registry_path.expanduser()
        elif isinstance(registry_path, str) and registry_path.strip():
            path = Path(registry_path).expanduser()
        else:
            raise ChannelRegistryValidationError(
                "registry_path must be a non-empty string or Path when provided",
                details={"registry_path": str(registry_path)},
            )
        if not path.exists():
            raise ChannelRegistryNotFoundError(
                f"Channel registry file not found: {path}",
                details={"path": str(path)},
            )
        if path.is_dir():
            raise ChannelRegistryValidationError(
                f"Channel registry path is a directory, expected a file: {path}",
                details={"path": str(path)},
            )
        return path

    for key in _ENV_VAR_KEYS:
        candidate = env.get(key)
        if candidate and candidate.strip():
            path = Path(candidate).expanduser()
            if path.exists() and path.is_file():
                return path
            raise ChannelRegistryNotFoundError(
                f"Channel registry file not found (from {key}): {path}",
                details={"path": str(path), "env_var": key},
            )

    cwd = Path.cwd()
    searched: list[str] = []
    for filename in _DEFAULT_FILENAMES:
        candidate = cwd / filename
        searched.append(str(candidate))
        if candidate.exists() and candidate.is_file():
            return candidate

    raise ChannelRegistryNotFoundError(
        "No channel registry file found. Provide --path or set THOMAS_CHANNEL_REGISTRY.",
        details={"searched": searched, "env_vars": list(_ENV_VAR_KEYS)},
    )


def _read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as e:  # pragma: no cover
        raise ChannelRegistryIOError(
            f"Failed to read channel registry file: {path}",
            details={"path": str(path), "errno": getattr(e, "errno", None)},
        ) from e


def _parse_registry(text: str, path: Path) -> Any:
    suffix = path.suffix.lower()
    try:
        if suffix == ".json":
            return json.loads(text)
        if suffix in {".yaml", ".yml"}:
            if yaml is None:
                raise ChannelRegistryUnsupportedFormatError(
                    "YAML registry files require PyYAML to be installed.",
                    details={"path": str(path)},
                )
            return yaml.safe_load(text)
        if suffix == ".toml":
            return tomllib.loads(text)

        # Unknown suffix: try YAML -> JSON -> TOML as a convenience.
        if yaml is not None:
            try:
                return yaml.safe_load(text)
            except Exception:
                pass
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            pass
        try:
            return tomllib.loads(text)
        except ValueError:
            pass

        raise ChannelRegistryUnsupportedFormatError(
            f"Unsupported channel registry file extension: {suffix or '<none>'}",
            details={"path": str(path), "suffix": suffix},
        )
    except ChannelRegistryError:
        raise
    except Exception as e:
        raise ChannelRegistryParseError(
            f"Failed to parse channel registry file: {path}",
            details={"path": str(path), "suffix": suffix, "error_type": type(e).__name__},
        ) from e


def _extract_channels(parsed: Any) -> list[MutableMapping[str, Any]]:
    """Extract a list of raw channel dicts from the parsed document."""
    if isinstance(parsed, list):
        channels = parsed
        meta: dict[str, Any] = {}
    elif isinstance(parsed, dict):
        if "channels" in parsed:
            channels = parsed["channels"]
            meta = {k: v for k, v in parsed.items() if k != "channels"}
        else:
            # Shorthand mapping form, with optional metadata.
            # We treat dict-valued entries as candidate channels and ignore a small
            # metadata set if present.
            meta = {}
            candidates: list[MutableMapping[str, Any]] = []
            for k, v in parsed.items():
                if not isinstance(v, dict):
                    meta[k] = v
                    continue
                entry = dict(v)
                entry.setdefault("name", k)
                candidates.append(entry)
            channels = candidates
            # If there are non-dict keys that aren't obvious metadata, surface it.
            unknown_meta = [k for k in meta.keys() if k not in {"version", "schema", "$schema"}]
            if unknown_meta:
                # Deterministic, but more forgiving than hard-failing on harmless metadata.
                # We only error if there are *zero* channel candidates.
                if not channels:
                    raise ChannelRegistryValidationError(
                        "Channel registry did not contain any channel entries",
                        details={"metadata_keys": sorted(list(meta.keys()))},
                    )
    else:
        raise ChannelRegistryValidationError(
            "Channel registry must be an object or list",
            details={"top_level_type": type(parsed).__name__},
        )

    if not isinstance(channels, list):
        raise ChannelRegistryValidationError(
            "The 'channels' field must be a list",
            details={"channels_type": type(channels).__name__},
        )

    out: list[MutableMapping[str, Any]] = []
    for idx, item in enumerate(channels):
        if not isinstance(item, dict):
            raise ChannelRegistryValidationError(
                "Each channel entry must be an object",
                details={"index": idx, "entry_type": type(item).__name__},
            )
        out.append(item)
    return out


def _normalize_channels(
    channels: Sequence[Mapping[str, Any]],
    *,
    env: Mapping[str, str],
    strict: bool,
) -> list[ChannelDefinition]:
    normalized: list[ChannelDefinition] = []
    seen_names: set[str] = set()

    for idx, raw in enumerate(channels):
        name = raw.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ChannelRegistryValidationError(
                "Channel 'name' must be a non-empty string",
                details={"index": idx},
            )
        name = name.strip()
        if name in seen_names:
            raise ChannelRegistryValidationError(
                f"Duplicate channel name: {name}",
                details={"name": name},
            )
        seen_names.add(name)

        kind = raw.get("kind") or raw.get("type") or raw.get("provider") or raw.get("integration")
        if not isinstance(kind, str) or not kind.strip():
            raise ChannelRegistryValidationError(
                "Channel 'kind' must be provided as a non-empty string (kind/type/provider/integration)",
                details={"name": name, "index": idx},
            )
        kind = kind.strip()

        enabled_raw = raw.get("enabled", True)
        if isinstance(enabled_raw, bool):
            enabled = enabled_raw
        else:
            raise ChannelRegistryValidationError(
                "Channel 'enabled' must be a boolean when provided",
                details={"name": name, "enabled_type": type(enabled_raw).__name__},
            )

        config: dict[str, Any] = {}

        # Explicit config block has priority
        if "config" in raw:
            cfg = raw.get("config") or {}
            if not isinstance(cfg, dict):
                raise ChannelRegistryValidationError(
                    "Channel 'config' must be an object when provided",
                    details={"name": name, "config_type": type(cfg).__name__},
                )
            config.update(cfg)

        # Allow nesting under provider name, e.g. {kind: {..}}
        nested = raw.get(kind)
        if isinstance(nested, dict):
            config.update(nested)

        # Merge remaining provider-specific keys
        reserved = {"name", "kind", "type", "provider", "integration", "enabled", "config", kind}
        for k, v in raw.items():
            if k in reserved:
                continue
            config[k] = v

        config_resolved = _resolve_env(config, env=env)
        if strict:
            _validate_known_channel_kinds(name=name, kind=kind, config=config_resolved)

        normalized.append(ChannelDefinition(name=name, kind=kind, config=config_resolved, enabled=enabled))

    return normalized


def _resolve_env(value: Any, *, env: Mapping[str, str]) -> Any:
    missing: set[str] = set()

    def walk(v: Any) -> Any:
        if isinstance(v, str):

            def repl(match: re.Match[str]) -> str:
                var = match.group(1)
                default = match.group(2)
                env_val = env.get(var)
                if env_val is not None and env_val != "":
                    return env_val
                if default is not None:
                    return default
                missing.add(var)
                # Leave literal in place for troubleshooting (even though we error)
                return match.group(0)

            return _ENV_PATTERN.sub(repl, v)

        if isinstance(v, list):
            return [walk(i) for i in v]
        if isinstance(v, tuple):
            return tuple(walk(i) for i in v)
        if isinstance(v, dict):
            return {k: walk(vv) for k, vv in v.items()}
        return v

    resolved = walk(value)
    if missing:
        raise ChannelRegistryValidationError(
            "Missing required environment variables for channel registry: " + ", ".join(sorted(missing)),
            details={"missing_env": sorted(missing)},
        )
    return resolved


def _validate_known_channel_kinds(*, name: str, kind: str, config: Mapping[str, Any]) -> None:
    kind_lower = kind.lower()

    if kind_lower == "telegram":
        token = config.get("token") or config.get("bot_token") or config.get("api_token")
        chat_id = config.get("chat_id") or config.get("chat") or config.get("chatId")

        missing: list[str] = []
        if token is None or (isinstance(token, str) and not token.strip()):
            missing.append("token")
        if chat_id is None or (isinstance(chat_id, str) and not chat_id.strip()):
            missing.append("chat_id")

        if missing:
            raise ChannelRegistryValidationError(
                f"Telegram channel '{name}' is missing required config field(s): {', '.join(missing)}",
                details={"name": name, "kind": kind, "missing": missing},
            )
