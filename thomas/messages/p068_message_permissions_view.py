"""Message permissions view (P068).

Thomas-native capability for retrieving the permissions a user has over a specific
message.

Backends:
1) Static permissions via configuration (ideal for tests/offline runs).
2) Remote permissions via an HTTP GET endpoint returning JSON.

Design goals:
- Clear, typed input/output contracts.
- Deterministic error codes for automation.
- Zero non-stdlib dependencies in this module.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Mapping, TypedDict


# ----------------------------
# Contracts
# ----------------------------


@dataclass(frozen=True, slots=True)
class MessagePermissionsViewRequest:
    """Input contract for viewing message permissions."""

    message_id: str
    user_id: str | None = None


@dataclass(frozen=True, slots=True)
class MessagePermissionsViewResult:
    """Output contract for viewing message permissions."""

    message_id: str
    user_id: str | None
    permissions: dict[str, bool]
    source: str  # "static" | "remote"


@dataclass(frozen=True, slots=True)
class MessagePermissionsViewConfig:
    """Configuration contract for resolving permissions."""

    static_permissions: dict[str, bool] | None = None
    endpoint: str | None = None
    token: str | None = None
    timeout_s: float = 10.0


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status_code: int
    text: str


class MessagePermissionsViewError(RuntimeError):
    """Deterministic error for message permissions view."""

    def __init__(self, *, code: str, message: str, details: Mapping[str, Any] | None = None):
        self.code = code
        self.details = dict(details or {})
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "details": self.details,
        }


class MessagePermissionsViewRequestDict(TypedDict, total=False):
    """JSON-friendly request shape."""

    message_id: str
    user_id: str


class MessagePermissionsViewResultDict(TypedDict):
    """JSON-friendly result shape."""

    message_id: str
    user_id: str | None
    permissions: dict[str, bool]
    source: str


HttpGetFn = Callable[[str, Mapping[str, str], Mapping[str, str], float], HttpResponse]


def request_from_dict(data: Mapping[str, Any]) -> MessagePermissionsViewRequest:
    """Parse a JSON-like mapping into a request object."""

    if not isinstance(data, Mapping):
        raise MessagePermissionsViewError(
            code="invalid_input",
            message="request payload must be an object",
            details={"type": type(data).__name__},
        )

    message_id = data.get("message_id")
    if not isinstance(message_id, str) or not message_id.strip():
        raise MessagePermissionsViewError(
            code="invalid_input",
            message="message_id is required",
            details={"field": "message_id"},
        )

    user_id = data.get("user_id")
    if user_id is not None and (not isinstance(user_id, str) or not user_id.strip()):
        raise MessagePermissionsViewError(
            code="invalid_input",
            message="user_id must be a non-empty string when provided",
            details={"field": "user_id"},
        )

    return MessagePermissionsViewRequest(message_id=message_id, user_id=user_id)


def view_message_permissions_from_dict(
    data: Mapping[str, Any],
    *,
    config: MessagePermissionsViewConfig | None = None,
    http_get: HttpGetFn | None = None,
) -> MessagePermissionsViewResultDict:
    """Convenience wrapper for JSON-in / JSON-out usage."""

    result = view_message_permissions(request_from_dict(data), config=config, http_get=http_get)
    return MessagePermissionsViewResultDict(
        message_id=result.message_id,
        user_id=result.user_id,
        permissions=result.permissions,
        source=result.source,
    )


def handle(
    payload: Mapping[str, Any],
    *,
    config: MessagePermissionsViewConfig | None = None,
    http_get: HttpGetFn | None = None,
) -> MessagePermissionsViewResultDict:
    """Generic entrypoint suitable for server dispatch tables."""

    return view_message_permissions_from_dict(payload, config=config, http_get=http_get)


# ----------------------------
# Configuration
# ----------------------------


_ENV_STATIC = "THOMAS_MESSAGE_PERMISSIONS_VIEW_STATIC"
_ENV_ENDPOINT = "THOMAS_MESSAGE_PERMISSIONS_VIEW_ENDPOINT"
_ENV_TOKEN = "THOMAS_MESSAGE_PERMISSIONS_VIEW_TOKEN"
_ENV_TIMEOUT = "THOMAS_MESSAGE_PERMISSIONS_VIEW_TIMEOUT_S"


def load_message_permissions_view_config() -> MessagePermissionsViewConfig:
    """Load config from environment variables."""

    static_raw = os.environ.get(_ENV_STATIC)
    endpoint = os.environ.get(_ENV_ENDPOINT)
    token = os.environ.get(_ENV_TOKEN)

    timeout_s = 10.0
    timeout_raw = os.environ.get(_ENV_TIMEOUT)
    if timeout_raw:
        try:
            timeout_s = float(timeout_raw)
        except ValueError as exc:
            raise MessagePermissionsViewError(
                code="invalid_input",
                message=f"Invalid {_ENV_TIMEOUT}: must be a number",
                details={"value": timeout_raw},
            ) from exc

    static_permissions: dict[str, bool] | None = None
    if static_raw is not None and static_raw.strip() != "":
        try:
            parsed = json.loads(static_raw)
        except json.JSONDecodeError as exc:
            raise MessagePermissionsViewError(
                code="invalid_input",
                message=f"Invalid {_ENV_STATIC}: must be valid JSON",
                details={"value": static_raw},
            ) from exc
        static_permissions = _coerce_permissions_mapping(parsed, context="env")

    if static_permissions is None and not endpoint:
        raise MessagePermissionsViewError(
            code="missing_config",
            message=(
                "Message permissions backend not configured. Set either "
                f"{_ENV_STATIC} (JSON mapping) or {_ENV_ENDPOINT} (URL)."
            ),
            details={"required": [_ENV_STATIC, _ENV_ENDPOINT]},
        )

    return MessagePermissionsViewConfig(
        static_permissions=static_permissions,
        endpoint=endpoint,
        token=token,
        timeout_s=timeout_s,
    )


# ----------------------------
# HTTP helper (stdlib)
# ----------------------------


def default_http_get(url: str, params: Mapping[str, str], headers: Mapping[str, str], timeout_s: float) -> HttpResponse:
    """Default HTTP GET implementation using urllib (stdlib)."""
    qs = urllib.parse.urlencode(params)
    full_url = f"{url}?{qs}" if qs else url
    req = urllib.request.Request(full_url, headers=dict(headers), method="GET")
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # nosec - controlled by config
        status = getattr(resp, "status", 200)
        body = resp.read()
        text = body.decode("utf-8", errors="replace")
        return HttpResponse(status_code=int(status), text=text)


# ----------------------------
# Core behavior
# ----------------------------


def view_message_permissions(
    request: MessagePermissionsViewRequest,
    *,
    config: MessagePermissionsViewConfig | None = None,
    http_get: HttpGetFn | None = None,
) -> MessagePermissionsViewResult:
    """Resolve permissions for a given message.

    Deterministic error codes:
      - invalid_input
      - missing_config
      - external_failure
    """

    msg_id = (request.message_id or "").strip()
    if not msg_id:
        raise MessagePermissionsViewError(
            code="invalid_input",
            message="message_id is required",
            details={"field": "message_id"},
        )

    cfg = config or load_message_permissions_view_config()

    if cfg.static_permissions is not None:
        return MessagePermissionsViewResult(
            message_id=msg_id,
            user_id=request.user_id,
            permissions=dict(cfg.static_permissions),
            source="static",
        )

    if not cfg.endpoint:
        raise MessagePermissionsViewError(
            code="missing_config",
            message="endpoint is required when static_permissions is not configured",
            details={"required": ["endpoint"]},
        )

    getter = http_get or default_http_get

    params: dict[str, str] = {"message_id": msg_id}
    if request.user_id:
        params["user_id"] = request.user_id

    headers: dict[str, str] = {"Accept": "application/json"}
    if cfg.token:
        headers["Authorization"] = f"Bearer {cfg.token}"

    try:
        resp = getter(cfg.endpoint, params, headers, cfg.timeout_s)
    except Exception as exc:
        raise MessagePermissionsViewError(
            code="external_failure",
            message="Failed to fetch permissions from remote backend",
            details={"endpoint": cfg.endpoint, "reason": str(exc)},
        ) from exc

    if resp.status_code != 200:
        raise MessagePermissionsViewError(
            code="external_failure",
            message="Remote backend returned non-200 response",
            details={
                "endpoint": cfg.endpoint,
                "status_code": resp.status_code,
                "body": resp.text[:500],
            },
        )

    try:
        payload: Any = json.loads(resp.text or "null")
    except json.JSONDecodeError as exc:
        raise MessagePermissionsViewError(
            code="external_failure",
            message="Remote backend returned invalid JSON",
            details={"endpoint": cfg.endpoint},
        ) from exc

    permissions_payload: Any = payload
    if isinstance(payload, dict) and "permissions" in payload:
        permissions_payload = payload.get("permissions")

    permissions = _coerce_permissions_mapping(permissions_payload, context="remote")

    return MessagePermissionsViewResult(
        message_id=msg_id,
        user_id=request.user_id,
        permissions=permissions,
        source="remote",
    )


def _coerce_permissions_mapping(value: Any, *, context: str) -> dict[str, bool]:
    """Coerce a mapping-like structure into a permissions dict."""

    code = "external_failure" if context == "remote" else "invalid_input"

    if not isinstance(value, dict):
        raise MessagePermissionsViewError(
            code=code,
            message="permissions must be a JSON object mapping permission names to booleans",
            details={"context": context, "type": type(value).__name__},
        )

    out: dict[str, bool] = {}
    for k, v in value.items():
        if not isinstance(k, str) or not k.strip():
            raise MessagePermissionsViewError(
                code=code,
                message="permission names must be non-empty strings",
                details={"context": context, "key": k},
            )
        if isinstance(v, bool):
            out[k] = v
        elif isinstance(v, int) and v in (0, 1):
            out[k] = bool(v)
        else:
            raise MessagePermissionsViewError(
                code=code,
                message="permission values must be boolean",
                details={"context": context, "permission": k, "value": v},
            )

    return out
