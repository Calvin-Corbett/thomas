"""Thomas-native channel provider interface contract.

Defines:
- request/response dataclasses
- deterministic error codes
- a small loader/adaptor for channel providers (e.g. Telegram)

Provider discovery (in order):
- thomas.channels.providers.<provider_id>
- thomas.integrations.<provider_id>

Provider shapes supported:
- get_provider(config=...) -> object with describe/health_check/send_message
- Provider(config=...) class -> instance with those methods
- module functions send_message/send (+ optional describe/health_check)
"""

from __future__ import annotations

import importlib
import inspect
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from types import ModuleType
from typing import Any, Protocol


class ChannelContractError(Exception):
    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details: dict[str, Any] = dict(details or {})


ERROR_INVALID_INPUT = "invalid_input"
ERROR_MISSING_CONFIG = "missing_config"
ERROR_PROVIDER_NOT_FOUND = "provider_not_found"
ERROR_PROVIDER_LOAD_FAILED = "provider_load_failed"
ERROR_PROVIDER_EXTERNAL_FAILURE = "provider_external_failure"


@dataclass(frozen=True)
class ContractErrorInfo:
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


ProviderAction = str  # "describe" | "health_check" | "send"


@dataclass(frozen=True)
class ProviderContractRequest:
    provider: str
    action: ProviderAction
    config: Mapping[str, Any] | None = None

    recipient: str | None = None
    message: str | None = None
    subject: str | None = None
    metadata: Mapping[str, Any] | None = None

    timeout_seconds: float | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class ProviderContractResponse:
    ok: bool
    provider: str
    action: ProviderAction
    result: dict[str, Any] | None = None
    error: ContractErrorInfo | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "provider": self.provider,
            "action": self.action,
            "result": self.result,
            "error": None
            if self.error is None
            else {"code": self.error.code, "message": self.error.message, "details": self.error.details},
        }


@dataclass(frozen=True)
class ProviderDescription:
    provider_id: str
    name: str
    capabilities: list[str]
    required_config_keys: list[str] = field(default_factory=list)
    optional_config_keys: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class HealthCheckResult:
    ok: bool
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SendMessageRequest:
    recipient: str
    message: str
    subject: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: float | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class SendMessageResult:
    delivered: bool
    message_id: str | None = None
    provider_response: dict[str, Any] = field(default_factory=dict)


class ChannelProvider(Protocol):
    provider_id: str

    def describe(self) -> ProviderDescription: ...

    def health_check(self) -> HealthCheckResult: ...

    def send_message(self, request: SendMessageRequest) -> SendMessageResult: ...


_PROVIDER_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
_ALLOWED_ACTIONS: set[str] = {"describe", "health_check", "send"}


def _validate_provider_id(provider_id: str) -> None:
    if not isinstance(provider_id, str) or not provider_id.strip():
        raise ChannelContractError(
            ERROR_INVALID_INPUT, "provider must be a non-empty string", details={"field": "provider"}
        )
    if not _PROVIDER_ID_RE.match(provider_id):
        raise ChannelContractError(
            ERROR_INVALID_INPUT, "provider contains invalid characters", details={"provider": provider_id}
        )


def _normalize_provider_id(provider_id: str) -> str:
    provider_id = provider_id.strip().replace("-", "_")
    return re.sub(r"[^a-zA-Z0-9_]", "_", provider_id)


def _candidate_modules(provider_id: str) -> list[str]:
    pid = _normalize_provider_id(provider_id)
    return [f"thomas.marketplace.channels.providers.{pid}", f"thomas.integrations.{pid}"]


def _safe_import(module_name: str) -> ModuleType | None:
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as e:
        missing = e.name or ""
        if missing == module_name or (missing and module_name.startswith(missing + ".")):
            return None
        raise


def _call_kwargs_by_signature(fn: Callable[..., Any], candidates: Mapping[str, Any]) -> Any:
    sig = inspect.signature(fn)
    params = sig.parameters
    kwargs = {k: v for k, v in candidates.items() if k in params and v is not None}
    return fn(**kwargs)


def _call_best_effort(fn: Callable[..., Any], candidates: Mapping[str, Any]) -> Any:
    try:
        return _call_kwargs_by_signature(fn, candidates)
    except TypeError:
        # tiny positional fallback set
        for args in ((), (candidates.get("config"),), (candidates.get("recipient"), candidates.get("message"))):
            try:
                return fn(*[a for a in args if a is not None])
            except TypeError:
                continue
        return fn()


def load_provider(provider_id: str, config: Mapping[str, Any] | None = None) -> ChannelProvider:
    _validate_provider_id(provider_id)
    cfg: Mapping[str, Any] = dict(config or {})

    for module_name in _candidate_modules(provider_id):
        try:
            module = _safe_import(module_name)
        except (ImportError, AttributeError, RuntimeError) as e:  # pragma: no cover
            raise ChannelContractError(
                ERROR_PROVIDER_LOAD_FAILED,
                f"provider module '{module_name}' failed to import",
                details={"provider": provider_id, "module": module_name, "exception": type(e).__name__},
            ) from e

        if module is None:
            continue

        return _adapt(provider_id, module, cfg)

    raise ChannelContractError(
        ERROR_PROVIDER_NOT_FOUND,
        f"unknown provider '{provider_id}'",
        details={"provider": provider_id, "candidates": _candidate_modules(provider_id)},
    )


def _adapt(provider_id: str, module: ModuleType, cfg: Mapping[str, Any]) -> ChannelProvider:
    factory = getattr(module, "get_provider", None)
    if callable(factory):
        obj = _call_best_effort(factory, {"config": cfg, "settings": cfg, "cfg": cfg})
        return _coerce(provider_id, obj, module, cfg)

    provider_cls = getattr(module, "Provider", None)
    if isinstance(provider_cls, type):
        try:
            obj = _call_best_effort(provider_cls, {"config": cfg, "settings": cfg, "cfg": cfg})
        except (RuntimeError, AttributeError, TypeError, ValueError) as e:  # pragma: no cover
            raise ChannelContractError(
                ERROR_PROVIDER_LOAD_FAILED,
                "provider class could not be constructed",
                details={"provider": provider_id, "module": module.__name__, "exception": type(e).__name__},
            ) from e
        return _coerce(provider_id, obj, module, cfg)

    return _ModuleFunctionProvider(provider_id=provider_id, module=module, config=cfg)


def _coerce(provider_id: str, obj: Any, module: ModuleType, cfg: Mapping[str, Any]) -> ChannelProvider:
    required = ("describe", "health_check", "send_message")
    if all(hasattr(obj, name) for name in required):
        if not hasattr(obj, "provider_id"):
            try:
                obj.provider_id = provider_id
            except (AttributeError, TypeError):
                pass
        return obj  # type: ignore[return-value]

    if isinstance(obj, ModuleType):
        return _ModuleFunctionProvider(provider_id=provider_id, module=obj, config=cfg)

    raise ChannelContractError(
        ERROR_PROVIDER_LOAD_FAILED,
        "provider object does not implement required methods",
        details={"provider": provider_id, "module": module.__name__, "object_type": type(obj).__name__},
    )


@dataclass
class _ModuleFunctionProvider:
    provider_id: str
    module: ModuleType
    config: Mapping[str, Any] = field(default_factory=dict)

    def describe(self) -> ProviderDescription:
        fn = getattr(self.module, "describe", None) or getattr(self.module, "describe_provider", None)
        if callable(fn):
            raw = _call_best_effort(fn, {"config": self.config, "settings": self.config, "cfg": self.config})
            return _coerce_description(self.provider_id, raw)

        caps: list[str] = []
        if callable(getattr(self.module, "send_message", None)) or callable(getattr(self.module, "send", None)):
            caps.append("send")
        if callable(getattr(self.module, "health_check", None)) or callable(getattr(self.module, "check_health", None)):
            caps.append("health_check")

        return ProviderDescription(provider_id=self.provider_id, name=self.provider_id, capabilities=caps)

    def health_check(self) -> HealthCheckResult:
        fn = getattr(self.module, "health_check", None) or getattr(self.module, "check_health", None)
        if not callable(fn):
            return HealthCheckResult(ok=True, details={"note": "provider does not implement health_check"})

        raw = _call_best_effort(fn, {"config": self.config, "settings": self.config, "cfg": self.config})
        if isinstance(raw, HealthCheckResult):
            return raw
        if isinstance(raw, Mapping):
            return HealthCheckResult(ok=bool(raw.get("ok", True)), details=dict(raw.get("details", raw)))
        return HealthCheckResult(ok=bool(raw), details={"raw": raw})

    def send_message(self, request: SendMessageRequest) -> SendMessageResult:
        fn = getattr(self.module, "send_message", None) or getattr(self.module, "send", None)
        if not callable(fn):
            raise ChannelContractError(
                ERROR_PROVIDER_LOAD_FAILED,
                "provider does not implement send_message",
                details={"provider": self.provider_id, "module": self.module.__name__},
            )

        candidates = {
            "config": self.config,
            "settings": self.config,
            "cfg": self.config,
            "recipient": request.recipient,
            "to": request.recipient,
            "chat_id": request.recipient,
            "message": request.message,
            "text": request.message,
            "body": request.message,
            "subject": request.subject,
            "metadata": request.metadata,
            "timeout_seconds": request.timeout_seconds,
            "timeout": request.timeout_seconds,
            "dry_run": request.dry_run,
        }
        raw = _call_best_effort(fn, candidates)

        if isinstance(raw, SendMessageResult):
            return raw
        if isinstance(raw, Mapping):
            return SendMessageResult(
                delivered=bool(raw.get("delivered", True)),
                message_id=raw.get("message_id"),
                provider_response=dict(raw.get("provider_response", raw)),
            )
        return SendMessageResult(delivered=bool(raw), provider_response={"raw": raw})


def _coerce_description(provider_id: str, raw: Any) -> ProviderDescription:
    if isinstance(raw, ProviderDescription):
        return raw
    if isinstance(raw, Mapping):
        return ProviderDescription(
            provider_id=str(raw.get("provider_id", provider_id)),
            name=str(raw.get("name", provider_id)),
            capabilities=[str(c) for c in list(raw.get("capabilities", []))],
            required_config_keys=[str(k) for k in list(raw.get("required_config_keys", raw.get("required", [])))],
            optional_config_keys=[str(k) for k in list(raw.get("optional_config_keys", raw.get("optional", [])))],
        )
    return ProviderDescription(provider_id=provider_id, name=provider_id, capabilities=[])


def run_provider_contract(request: ProviderContractRequest) -> ProviderContractResponse:
    try:
        _validate_request(request)
        provider = load_provider(request.provider, config=request.config)

        if request.action == "describe":
            desc = provider.describe()
            return ProviderContractResponse(
                ok=True, provider=request.provider, action=request.action, result=asdict(desc)
            )

        if request.action == "health_check":
            hc = provider.health_check()
            return ProviderContractResponse(
                ok=True, provider=request.provider, action=request.action, result={"ok": hc.ok, "details": hc.details}
            )

        assert request.config is not None

        # Enforce required config keys when available.
        try:
            desc = provider.describe()
            missing = [
                k for k in desc.required_config_keys if k not in request.config or request.config.get(k) in (None, "")
            ]
            if missing:
                raise ChannelContractError(
                    ERROR_MISSING_CONFIG,
                    "config missing required keys",
                    details={"provider": request.provider, "missing_keys": missing},
                )
        except ChannelContractError:
            raise
        except (RuntimeError, AttributeError, KeyError, ValueError):
            pass  # pragma: no cover

        send_req = SendMessageRequest(
            recipient=str(request.recipient),
            message=str(request.message),
            subject=request.subject,
            metadata=dict(request.metadata or {}),
            timeout_seconds=request.timeout_seconds,
            dry_run=bool(request.dry_run),
        )
        send_res = provider.send_message(send_req)
        return ProviderContractResponse(
            ok=True,
            provider=request.provider,
            action=request.action,
            result={
                "delivered": send_res.delivered,
                "message_id": send_res.message_id,
                "provider_response": send_res.provider_response,
            },
        )

    except ChannelContractError as e:
        return ProviderContractResponse(
            ok=False,
            provider=getattr(request, "provider", ""),
            action=getattr(request, "action", ""),
            error=ContractErrorInfo(code=e.code, message=str(e), details=dict(e.details)),
        )
    except (
        RuntimeError,
        AttributeError,
        ConnectionError,
        TimeoutError,
        json.JSONDecodeError,
        ValueError,
        KeyError,
    ) as e:  # pragma: no cover
        return ProviderContractResponse(
            ok=False,
            provider=getattr(request, "provider", ""),
            action=getattr(request, "action", ""),
            error=ContractErrorInfo(
                code=ERROR_PROVIDER_EXTERNAL_FAILURE,
                message="provider call failed",
                details={"exception": type(e).__name__, "message": str(e)},
            ),
        )


def _validate_request(request: ProviderContractRequest) -> None:
    if not isinstance(request, ProviderContractRequest):
        raise ChannelContractError(ERROR_INVALID_INPUT, "request must be a ProviderContractRequest")

    _validate_provider_id(request.provider)

    if request.action not in _ALLOWED_ACTIONS:
        raise ChannelContractError(
            ERROR_INVALID_INPUT,
            "action must be one of: describe, health_check, send",
            details={"action": request.action},
        )

    if request.action == "send":
        if request.config is None:
            raise ChannelContractError(
                ERROR_MISSING_CONFIG, "config is required for send", details={"provider": request.provider}
            )
        if not isinstance(request.config, Mapping):
            raise ChannelContractError(ERROR_INVALID_INPUT, "config must be a mapping", details={"field": "config"})
        if request.recipient is None or not str(request.recipient).strip():
            raise ChannelContractError(
                ERROR_INVALID_INPUT, "recipient is required for send", details={"field": "recipient"}
            )
        if request.message is None or not str(request.message).strip():
            raise ChannelContractError(
                ERROR_INVALID_INPUT, "message is required for send", details={"field": "message"}
            )

    if request.metadata is not None and not isinstance(request.metadata, Mapping):
        raise ChannelContractError(ERROR_INVALID_INPUT, "metadata must be a mapping", details={"field": "metadata"})

    if request.timeout_seconds is not None:
        try:
            t = float(request.timeout_seconds)
        except (TypeError, ValueError):
            raise ChannelContractError(
                ERROR_INVALID_INPUT, "timeout_seconds must be a number", details={"field": "timeout_seconds"}
            )
        if t <= 0:
            raise ChannelContractError(
                ERROR_INVALID_INPUT, "timeout_seconds must be > 0", details={"field": "timeout_seconds"}
            )


def dumps_response_json(response: ProviderContractResponse) -> str:
    return json.dumps(response.to_dict(), sort_keys=True, indent=2)
