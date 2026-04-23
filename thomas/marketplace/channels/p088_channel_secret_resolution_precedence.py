from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class SecretResolutionError(Exception):
    """Base error for channel secret resolution failures.

    The error surface is designed to be deterministic and machine-readable.
    """

    code: str = "secret_resolution_error"

    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details: dict[str, Any] = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error": {
                "code": self.code,
                "message": str(self),
                "details": self.details,
            },
        }


class InvalidSecretRequestError(SecretResolutionError):
    """Raised when the resolution request is malformed."""

    code = "invalid_secret_request"


class SecretNotFoundError(SecretResolutionError):
    """Raised when no secret can be resolved from any configured source."""

    code = "secret_not_found"


class SecretSourceError(SecretResolutionError):
    """Raised when an explicitly chosen source cannot be read/resolved."""

    code = "secret_source_error"


class SecretSource(str, Enum):
    CLI = "cli"
    CHANNEL = "channel"
    ENV = "env"
    CONFIG = "config"


class SecretSpecType(str, Enum):
    LITERAL = "literal"
    ENV = "env"
    FILE = "file"


@dataclass(frozen=True, slots=True)
class ChannelSecretRequest:
    """Inputs for secret resolution.

    Precedence (highest → lowest):
    1) cli_spec
    2) channel_spec
    3) env_var_names (or provider defaults when omitted)
    4) config_spec
    """

    provider: str
    secret_key: str
    cli_spec: str | None = None
    channel_spec: str | None = None
    config_spec: str | None = None
    env_var_names: Sequence[str] = field(default_factory=tuple)
    allow_empty: bool = False


@dataclass(frozen=True, slots=True)
class ChannelSecretResolution:
    """Output of secret resolution."""

    provider: str
    secret_key: str
    value: str
    source: SecretSource
    spec_type: SecretSpecType
    details: dict[str, Any] = field(default_factory=dict)

    def redacted_value(self) -> str:
        return redact_secret(self.value)

    def to_dict(self, *, include_secret: bool = False) -> dict[str, Any]:
        return {
            "ok": True,
            "provider": self.provider,
            "secret_key": self.secret_key,
            "source": self.source.value,
            "spec_type": self.spec_type.value,
            "details": dict(self.details),
            "secret": self.value if include_secret else self.redacted_value(),
            "secret_len": len(self.value),
        }


def redact_secret(secret: str) -> str:
    """Return a stable redacted representation suitable for logs."""

    if secret == "":
        return ""
    if len(secret) <= 4:
        return "*" * len(secret)
    return ("*" * (len(secret) - 4)) + secret[-4:]


def _default_env_var_names(provider: str, secret_key: str) -> tuple[str, ...]:
    p = provider.strip().upper().replace("-", "_")
    k = secret_key.strip().upper().replace("-", "_")

    # Generic defaults: THOMAS_<PROVIDER>_<SECRET_KEY> then <PROVIDER>_<SECRET_KEY>
    candidates: list[str] = [
        f"THOMAS_{p}_{k}",
        f"{p}_{k}",
    ]

    # Pragmatic Telegram defaults: BOT_TOKEN is the dominant convention.
    if p == "TELEGRAM" and k in {"TOKEN", "BOT_TOKEN", "BOTTOKEN"}:
        candidates = [
            "THOMAS_TELEGRAM_BOT_TOKEN",
            "TELEGRAM_BOT_TOKEN",
            "THOMAS_TELEGRAM_TOKEN",
            "TELEGRAM_TOKEN",
        ] + candidates

    # De-dupe while preserving order.
    seen: set[str] = set()
    ordered: list[str] = []
    for name in candidates:
        if name not in seen:
            ordered.append(name)
            seen.add(name)
    return tuple(ordered)


def _parse_spec(spec: str) -> tuple[SecretSpecType, dict[str, Any]]:
    s = spec.strip()
    if s == "":
        raise InvalidSecretRequestError("Secret spec must be non-empty.")

    if s.startswith("env:"):
        name = s[4:].strip()
        if not name:
            raise InvalidSecretRequestError("env: secret spec must include an environment variable name.")
        return (SecretSpecType.ENV, {"env_var": name})

    # Common config interpolation style: ${NAME}
    if s.startswith("${") and s.endswith("}") and len(s) > 3:
        name = s[2:-1].strip()
        if not name:
            raise InvalidSecretRequestError("${...} secret spec must include an environment variable name.")
        return (SecretSpecType.ENV, {"env_var": name})

    if s.startswith("file:"):
        path_str = s[5:].strip()
        if not path_str:
            raise InvalidSecretRequestError("file: secret spec must include a file path.")
        return (SecretSpecType.FILE, {"path": path_str})

    return (SecretSpecType.LITERAL, {"literal": s})


def _read_file(path_str: str) -> str:
    # Deterministic behavior: interpret relative paths relative to the current working directory.
    return Path(path_str).read_text(encoding="utf-8")


PRECEDENCE_ORDER: tuple[SecretSource, ...] = (
    SecretSource.CLI,
    SecretSource.CHANNEL,
    SecretSource.ENV,
    SecretSource.CONFIG,
)


def get_precedence_order() -> tuple[str, ...]:
    """Return the precedence order as stable strings."""

    return tuple(src.value for src in PRECEDENCE_ORDER)


def resolve_channel_secret(
    request: ChannelSecretRequest,
    *,
    env: Mapping[str, str] | None = None,
    read_file: Callable[[str], str] | None = None,
) -> ChannelSecretResolution:
    """Resolve a channel secret using Thomas precedence rules.

    This function is intentionally small and dependency-free so it can be used
    from both CLI code and integrations.

    Secret specs:
    - "literal" value: treated as the secret itself
    - "env:NAME" or "${NAME}": read from environment variable NAME
    - "file:/path": read from file contents (UTF-8), then stripped
    """

    env_map: Mapping[str, str] = env if env is not None else __import__("os").environ
    file_reader = read_file or _read_file

    provider = request.provider.strip()
    secret_key = request.secret_key.strip()
    if not provider:
        raise InvalidSecretRequestError("provider must be a non-empty string.")
    if not secret_key:
        raise InvalidSecretRequestError("secret_key must be a non-empty string.")

    def _finalize(
        value: str,
        *,
        source: SecretSource,
        spec_type: SecretSpecType,
        details: dict[str, Any],
    ) -> ChannelSecretResolution:
        if (not request.allow_empty) and value == "":
            raise SecretSourceError(
                "Resolved secret is empty.",
                details={
                    "provider": provider,
                    "secret_key": secret_key,
                    "source": source.value,
                    **details,
                },
            )
        return ChannelSecretResolution(
            provider=provider,
            secret_key=secret_key,
            value=value,
            source=source,
            spec_type=spec_type,
            details=details,
        )

    def _resolve_explicit_spec(spec: str, *, source: SecretSource) -> ChannelSecretResolution:
        spec_type, meta = _parse_spec(spec)

        if spec_type is SecretSpecType.LITERAL:
            return _finalize(meta["literal"], source=source, spec_type=spec_type, details={})

        if spec_type is SecretSpecType.ENV:
            var = str(meta["env_var"])
            value = env_map.get(var)
            if value is None:
                raise SecretSourceError(
                    "Environment variable referenced by secret spec is not set.",
                    details={
                        "provider": provider,
                        "secret_key": secret_key,
                        "env_var": var,
                        "source": source.value,
                    },
                )
            return _finalize(value, source=source, spec_type=spec_type, details={"env_var": var})

        if spec_type is SecretSpecType.FILE:
            path_str = str(meta["path"])
            try:
                content = file_reader(path_str)
            except OSError as e:
                raise SecretSourceError(
                    "Failed to read secret file referenced by secret spec.",
                    details={
                        "provider": provider,
                        "secret_key": secret_key,
                        "path": path_str,
                        "source": source.value,
                        "os_error": str(e),
                    },
                ) from e
            return _finalize(
                content.strip(),
                source=source,
                spec_type=spec_type,
                details={"path": path_str},
            )

        # Future-proofing: enum exhaustiveness.
        raise InvalidSecretRequestError(
            "Unsupported secret spec type.",
            details={"provider": provider, "secret_key": secret_key, "source": source.value},
        )

    # 1) CLI spec (if present) is authoritative; failures are surfaced.
    if request.cli_spec is not None:
        return _resolve_explicit_spec(request.cli_spec, source=SecretSource.CLI)

    # 2) Channel configuration overrides env/config fallbacks.
    if request.channel_spec is not None:
        return _resolve_explicit_spec(request.channel_spec, source=SecretSource.CHANNEL)

    # 3) Environment variables (best-effort; missing/empty values fall through).
    env_names = tuple(request.env_var_names) if request.env_var_names else _default_env_var_names(provider, secret_key)
    for var in env_names:
        if var not in env_map:
            continue
        value = env_map.get(var, "")
        if value == "" and not request.allow_empty:
            # Treat empty as unset for fallback purposes.
            continue
        return _finalize(
            value,
            source=SecretSource.ENV,
            spec_type=SecretSpecType.ENV,
            details={"env_var": var},
        )

    # 4) Global/integration config.
    if request.config_spec is not None:
        return _resolve_explicit_spec(request.config_spec, source=SecretSource.CONFIG)

    attempted = {
        "cli_spec_provided": request.cli_spec is not None,
        "channel_spec_provided": request.channel_spec is not None,
        "env_var_names": list(env_names),
        "config_spec_provided": request.config_spec is not None,
    }
    raise SecretNotFoundError(
        f"No secret could be resolved for provider='{provider}' and secret_key='{secret_key}'.",
        details={
            "provider": provider,
            "secret_key": secret_key,
            "attempted": attempted,
        },
    )


def resolve_secret_value(
    *,
    provider: str,
    secret_key: str,
    cli: str | None = None,
    channel: str | None = None,
    config: str | None = None,
    env_var_names: Sequence[str] = (),
    env: Mapping[str, str] | None = None,
    read_file: Callable[[str], str] | None = None,
    allow_empty: bool = False,
) -> ChannelSecretResolution:
    """Convenience wrapper for call sites that don't want to build dataclasses."""

    return resolve_channel_secret(
        ChannelSecretRequest(
            provider=provider,
            secret_key=secret_key,
            cli_spec=cli,
            channel_spec=channel,
            config_spec=config,
            env_var_names=env_var_names,
            allow_empty=allow_empty,
        ),
        env=env,
        read_file=read_file,
    )
