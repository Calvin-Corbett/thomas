"""Channel provider contract tests.

This module implements a provider-focused diagnostic runner for Thomas channel
integrations.

Design goals:
* Thomas-native (no OpenClaw naming reuse)
* Deterministic failures: stable error codes for automation
* Optional external checks: safe, read-only upstream API calls when possible
* Machine-readable output: JSON report + JSON schema
"""

from __future__ import annotations

import importlib
import inspect
import json
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

# ------------------------------- Public contracts ----------------------------


@dataclass(frozen=True, slots=True)
class ProviderContractTestRequest:
    """Input contract for contract tests."""

    provider: str
    config: Mapping[str, Any] | None = None
    run_external: bool = False
    timeout_seconds: float = 5.0


@dataclass(frozen=True, slots=True)
class ContractTestCheckResult:
    """Result for a single check."""

    name: str
    ok: bool
    message: str | None = None
    data: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ContractTestError:
    """Deterministic error container."""

    code: str
    message: str
    details: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ProviderContractTestReport:
    """Output contract for contract tests."""

    provider: str
    ok: bool
    checks: list[ContractTestCheckResult] = field(default_factory=list)
    errors: list[ContractTestError] = field(default_factory=list)
    duration_ms: int | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["checks"] = [asdict(c) for c in self.checks]
        payload["errors"] = [asdict(e) for e in self.errors]
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)


# ------------------------------ Deterministic codes --------------------------


ERROR_INVALID_REQUEST = "invalid_request"
ERROR_PROVIDER_NOT_FOUND = "provider_not_found"
ERROR_PROVIDER_IMPORT_FAILED = "provider_import_failed"
ERROR_MISSING_CONFIG = "missing_config"
ERROR_EXTERNAL_FAILURE = "external_failure"


def report_json_schema() -> Mapping[str, Any]:
    """JSON schema for ProviderContractTestReport."""

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "ProviderContractTestReport",
        "type": "object",
        "required": ["provider", "ok", "checks", "errors"],
        "properties": {
            "provider": {"type": "string"},
            "ok": {"type": "boolean"},
            "duration_ms": {"type": ["integer", "null"], "minimum": 0},
            "checks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["name", "ok"],
                    "properties": {
                        "name": {"type": "string"},
                        "ok": {"type": "boolean"},
                        "message": {"type": ["string", "null"]},
                        "data": {"type": ["object", "null"]},
                    },
                    "additionalProperties": False,
                },
            },
            "errors": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["code", "message"],
                    "properties": {
                        "code": {"type": "string"},
                        "message": {"type": "string"},
                        "details": {"type": ["object", "null"]},
                    },
                    "additionalProperties": False,
                },
            },
        },
        "additionalProperties": False,
    }


def run_channel_provider_contract_tests(
    request: ProviderContractTestRequest,
) -> ProviderContractTestReport:
    """Run contract tests for a channel provider.

    This function is exception-safe by design: it converts failures into
    deterministic error codes inside the returned report.
    """

    started = time.monotonic()

    provider = (request.provider or "").strip().lower()
    if not provider:
        return _finalize_report(
            provider="",
            ok=False,
            checks=[],
            errors=[
                ContractTestError(
                    code=ERROR_INVALID_REQUEST,
                    message="Provider is required.",
                    details={"field": "provider"},
                )
            ],
            started=started,
        )

    if request.config is not None and not isinstance(request.config, Mapping):
        return _finalize_report(
            provider=provider,
            ok=False,
            checks=[],
            errors=[
                ContractTestError(
                    code=ERROR_INVALID_REQUEST,
                    message="config must be an object/mapping.",
                    details={"field": "config", "type": type(request.config).__name__},
                )
            ],
            started=started,
        )

    try:
        timeout_seconds = float(request.timeout_seconds)
    except (ConnectionError, TimeoutError, RuntimeError):
        timeout_seconds = -1.0

    if timeout_seconds <= 0:
        return _finalize_report(
            provider=provider,
            ok=False,
            checks=[],
            errors=[
                ContractTestError(
                    code=ERROR_INVALID_REQUEST,
                    message="timeout_seconds must be > 0.",
                    details={"field": "timeout_seconds", "value": request.timeout_seconds},
                )
            ],
            started=started,
        )

    if provider == "telegram":
        checks, errors = _telegram_contract_checks(
            config=request.config,
            run_external=bool(request.run_external),
            timeout_seconds=timeout_seconds,
        )
        ok = all(c.ok for c in checks) and not errors
        return _finalize_report(
            provider="telegram",
            ok=ok,
            checks=checks,
            errors=errors,
            started=started,
        )

    return _finalize_report(
        provider=provider,
        ok=False,
        checks=[],
        errors=[
            ContractTestError(
                code=ERROR_PROVIDER_NOT_FOUND,
                message=f"Unknown provider: {provider}",
                details={"provider": provider},
            )
        ],
        started=started,
    )


def _finalize_report(
    *,
    provider: str,
    ok: bool,
    checks: list[ContractTestCheckResult],
    errors: list[ContractTestError],
    started: float,
) -> ProviderContractTestReport:
    duration_ms = int((time.monotonic() - started) * 1000)
    return ProviderContractTestReport(
        provider=provider,
        ok=ok,
        checks=checks,
        errors=errors,
        duration_ms=duration_ms,
    )


# ----------------------------- Telegram implementation -----------------------


def _telegram_contract_checks(
    *,
    config: Mapping[str, Any] | None,
    run_external: bool,
    timeout_seconds: float,
) -> tuple[list[ContractTestCheckResult], list[ContractTestError]]:
    checks: list[ContractTestCheckResult] = []
    errors: list[ContractTestError] = []

    module_name = "thomas.integrations.telegram"
    try:
        telegram_mod = importlib.import_module(module_name)
        checks.append(
            ContractTestCheckResult(
                name="import",
                ok=True,
                message=f"Imported {module_name}",
            )
        )
    except (ImportError, AttributeError, RuntimeError) as exc:
        errors.append(
            ContractTestError(
                code=ERROR_PROVIDER_IMPORT_FAILED,
                message=f"Failed to import {module_name}",
                details={
                    "module": module_name,
                    "exception_type": type(exc).__name__,
                    "exception": str(exc),
                },
            )
        )
        checks.append(
            ContractTestCheckResult(
                name="import",
                ok=False,
                message=f"Import failed: {type(exc).__name__}",
            )
        )
        return checks, errors

    token = _resolve_config_value(
        config,
        keys=("token", "bot_token", "telegram_token", "telegram_bot_token"),
        env_vars=("THOMAS_TELEGRAM_BOT_TOKEN", "TELEGRAM_BOT_TOKEN", "TELEGRAM_TOKEN"),
    )
    chat_id = _resolve_config_value(
        config,
        keys=("chat_id", "telegram_chat_id", "channel_id", "telegram_channel_id"),
        env_vars=("THOMAS_TELEGRAM_CHAT_ID", "TELEGRAM_CHAT_ID", "TELEGRAM_CHANNEL_ID"),
    )

    missing: list[str] = []
    if token in (None, ""):
        missing.append("token")
    if chat_id in (None, ""):
        missing.append("chat_id")

    if missing:
        errors.append(
            ContractTestError(
                code=ERROR_MISSING_CONFIG,
                message="Missing required Telegram configuration.",
                details={"missing": missing},
            )
        )
        checks.append(
            ContractTestCheckResult(
                name="config",
                ok=False,
                message="Missing required configuration keys.",
                data={"missing": missing},
            )
        )
    else:
        checks.append(
            ContractTestCheckResult(
                name="config",
                ok=True,
                message="Required configuration present.",
            )
        )

    api_ok, api_msg, api_data = _telegram_api_surface_check(telegram_mod)
    checks.append(
        ContractTestCheckResult(
            name="api_surface",
            ok=api_ok,
            message=api_msg,
            data=api_data,
        )
    )

    if run_external:
        if token in (None, ""):
            errors.append(
                ContractTestError(
                    code=ERROR_MISSING_CONFIG,
                    message="External check requires Telegram token.",
                    details={"missing": ["token"]},
                )
            )
            checks.append(
                ContractTestCheckResult(
                    name="external_health",
                    ok=False,
                    message="External check skipped: missing token.",
                )
            )
        else:
            ok, msg, details = _telegram_external_health_check(
                telegram_mod,
                token=str(token),
                timeout_seconds=float(timeout_seconds),
            )
            checks.append(
                ContractTestCheckResult(
                    name="external_health",
                    ok=ok,
                    message=msg,
                    data=details,
                )
            )
            if not ok:
                errors.append(
                    ContractTestError(
                        code=ERROR_EXTERNAL_FAILURE,
                        message=msg or "External health check failed.",
                        details=details,
                    )
                )

    return checks, errors


def _resolve_config_value(
    config: Mapping[str, Any] | None,
    *,
    keys: tuple[str, ...],
    env_vars: tuple[str, ...],
) -> Any | None:
    if config:
        lowered = {str(k).lower(): v for k, v in config.items()}
        for key in keys:
            val = lowered.get(key.lower())
            if val not in (None, ""):
                return val

    for env in env_vars:
        val = os.getenv(env)
        if val not in (None, ""):
            return val

    return None


def _telegram_api_surface_check(telegram_mod: Any) -> tuple[bool, str, Mapping[str, Any] | None]:
    """Check for a plausible send API on the Telegram integration module."""

    explicit_candidates = [
        "send_message",
        "send",
        "post_message",
        "TelegramClient",
        "TelegramIntegration",
        "TelegramChannel",
    ]
    for name in explicit_candidates:
        if hasattr(telegram_mod, name):
            return True, f"Found Telegram integration symbol: {name}", {"symbol": name}

    sendish: list[str] = []
    for attr_name in dir(telegram_mod):
        if "send" not in attr_name.lower():
            continue
        try:
            attr = getattr(telegram_mod, attr_name)
        except (ImportError, AttributeError, RuntimeError):
            continue
        if callable(attr):
            sendish.append(attr_name)

    if sendish:
        return True, "Found send-like callable(s) in Telegram integration.", {"candidates": sorted(sendish)}

    return False, "No obvious Telegram send API found.", {"expected_any_of": explicit_candidates}


def _telegram_external_health_check(
    telegram_mod: Any,
    *,
    token: str,
    timeout_seconds: float,
) -> tuple[bool, str, Mapping[str, Any] | None]:
    """External health check (read-only)."""

    for func_name in (
        "healthcheck",
        "health_check",
        "ping",
        "verify",
        "verify_token",
        "get_me",
        "getMe",
    ):
        fn = getattr(telegram_mod, func_name, None)
        if callable(fn):
            try:
                result = _call_with_supported_args(
                    fn,
                    token=token,
                    bot_token=token,
                    timeout=timeout_seconds,
                    timeout_seconds=timeout_seconds,
                )
                ok = _truthy_ok(result)
                return (
                    ok,
                    "Integration health check passed." if ok else "Integration health check failed.",
                    {"function": func_name},
                )
            except (RuntimeError, ValueError, KeyError, AttributeError, TypeError) as exc:
                return (
                    False,
                    "Integration health check errored.",
                    {"function": func_name, "exception_type": type(exc).__name__, "exception": str(exc)},
                )

    # Fall back to Telegram getMe using stdlib urllib to avoid a hard dependency.
    import urllib.error
    import urllib.request

    url = f"https://api.telegram.org/bot{token}/getMe"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "thomas-contract-tests/1.0"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:  # nosec B310
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        body_bytes = None
        try:
            body_bytes = exc.read()
        except (ConnectionError, TimeoutError, RuntimeError):
            body_bytes = None
        return (
            False,
            "Telegram getMe returned an HTTP error.",
            {
                "endpoint": "getMe",
                "http_status": getattr(exc, "code", None),
                "body": body_bytes.decode("utf-8", errors="replace")
                if isinstance(body_bytes, (bytes, bytearray))
                else None,
            },
        )
    except (json.JSONDecodeError, ValueError, KeyError) as exc:
        return (
            False,
            "Telegram getMe request failed.",
            {"endpoint": "getMe", "exception_type": type(exc).__name__, "exception": str(exc)},
        )

    try:
        data = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, ValueError, KeyError) as exc:
        return (
            False,
            "Telegram getMe returned invalid JSON.",
            {"endpoint": "getMe", "exception_type": type(exc).__name__, "exception": str(exc)},
        )

    ok = bool(isinstance(data, dict) and data.get("ok") is True)
    if ok:
        return True, "Telegram getMe succeeded.", {"endpoint": "getMe"}

    return False, "Telegram getMe returned a non-ok response.", {"endpoint": "getMe", "response": data}


def _call_with_supported_args(fn: Callable[..., Any], /, **kwargs: Any) -> Any:
    """Call a function, filtering kwargs to the supported signature."""

    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return fn(**kwargs)

    params = sig.parameters
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return fn(**kwargs)

    supported = {k: v for k, v in kwargs.items() if k in params}
    return fn(**supported)


def _truthy_ok(result: Any) -> bool:
    if result is None:
        return False
    if isinstance(result, bool):
        return result
    if isinstance(result, Mapping):
        if "ok" in result:
            return bool(result.get("ok"))
        if "success" in result:
            return bool(result.get("success"))
    return bool(result)
