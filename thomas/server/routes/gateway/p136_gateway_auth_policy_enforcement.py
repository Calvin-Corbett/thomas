from __future__ import annotations

"""\
Gateway auth policy enforcement.

This module implements a Thomas-native gateway authentication policy layer.

Pieces:
- Policy loader (from aiohttp Application config and/or environment variables)
- aiohttp middleware that enforces the policy
- policy introspection endpoint (no secrets) for automation

Policy model is intentionally small:
- disabled (default)
- token (require one of N shared tokens)

Configuration sources (highest precedence first):
1) request.app[...] (Mapping) with any of:
   - "gateway_auth_policy": dict
   - "gateway_auth": dict
   - "gateway_auth_mode": str
   - "gateway_auth_token": str | list[str]
   - "gateway_auth_tokens": list[str] | str (comma-separated)
   - "gateway_auth_scope": str
   - "gateway_auth_allow_query_param": bool
   - "gateway_auth_exempt_paths": list[str] | str (comma-separated)
2) Environment variables:
   - THOMAS_GATEWAY_AUTH_POLICY (JSON object)
   - THOMAS_GATEWAY_AUTH_POLICY_FILE (path to JSON file)
   - THOMAS_GATEWAY_AUTH_MODE
   - THOMAS_GATEWAY_AUTH_TOKEN
   - THOMAS_GATEWAY_AUTH_TOKENS (comma-separated)
   - THOMAS_GATEWAY_AUTH_SCOPE
   - THOMAS_GATEWAY_AUTH_ALLOW_QUERY_PARAM
   - THOMAS_GATEWAY_AUTH_EXEMPT_PATHS (comma-separated)
   - THOMAS_GATEWAY_AUTH_RATE_LIMIT_ENABLED
   - THOMAS_GATEWAY_AUTH_RATE_LIMIT_MAX_FAILURES
   - THOMAS_GATEWAY_AUTH_RATE_LIMIT_WINDOW_SECONDS

Auth presentation (first match wins):
- Authorization: Bearer <token>
- X-Thomas-Gateway-Token: <token>
- X-Gateway-Token: <token>
- Query params token/auth/gateway_token (if allow_query_param is true; default true)
- Cookies thomas_gateway_token/gateway_token (lowest precedence)

Deterministic error responses:
{
  "ok": false,
  "error": {"code": "...", "message": "..."}
}
"""

import asyncio
import hashlib
import hmac
import ipaddress
import json
import os
import time
import weakref
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, TypedDict

from aiohttp import web


class GatewayAuthPolicyError(Exception):
    """Base error for gateway auth policy failures."""


class GatewayAuthPolicyConfigError(GatewayAuthPolicyError):
    """Raised when the configured policy is invalid or incomplete."""


class GatewayAuthPolicyExternalError(GatewayAuthPolicyError):
    """Raised when policy configuration cannot be loaded due to an external error (e.g. file IO)."""


class GatewayAuthPolicyConfig(TypedDict, total=False):
    mode: str
    token: str
    tokens: list[str]
    scope: str
    allow_query_param: bool
    exempt_paths: list[str]
    rate_limit_enabled: bool
    rate_limit_max_failures: int
    rate_limit_window_seconds: int


class GatewayAuthPolicyRateLimitInfo(TypedDict):
    enabled: bool
    max_failures: int
    window_seconds: int


class GatewayAuthPolicyInfo(TypedDict):
    mode: str
    required: bool
    scope: str
    token_configured: bool
    allow_query_param: bool
    accepted_headers: list[str]
    accepted_query_params: list[str]
    exempt_paths: list[str]
    rate_limit: GatewayAuthPolicyRateLimitInfo


GatewayAuthMode = Literal["disabled", "token"]
GatewayAuthScope = Literal["auto", "prefix", "all"]


@dataclass(frozen=True)
class GatewayAuthPolicy:
    mode: GatewayAuthMode = "disabled"
    tokens: tuple[str, ...] = ()
    scope: GatewayAuthScope = "auto"
    allow_query_param: bool = True
    exempt_paths: tuple[str, ...] = ()
    rate_limit_enabled: bool = True
    rate_limit_max_failures: int = 8
    rate_limit_window_seconds: int = 60

    @property
    def required(self) -> bool:
        return self.mode != "disabled"


@dataclass(frozen=True)
class GatewayAuthDecision:
    allowed: bool
    http_status: int = 200
    code: str | None = None
    message: str | None = None


# Cache policies without mutating aiohttp Application (avoid aiohttp deprecation warnings).
_POLICY_CACHE: weakref.WeakKeyDictionary[web.Application, GatewayAuthPolicy] = weakref.WeakKeyDictionary()
_APP_REGISTERED: web.AppKey[bool] = web.AppKey("__p136_gateway_auth_policy_registered", bool)
_AUTH_FAILURES_CACHE: weakref.WeakKeyDictionary[web.Application, dict[str, Any]] = weakref.WeakKeyDictionary()
_AUTH_FAILURE_LOCKS: weakref.WeakKeyDictionary[web.Application, asyncio.Lock] = weakref.WeakKeyDictionary()

# In auto/prefix modes, enforcement targets these gateway-ish paths.
#
# `/v1/gateway` was missing, so four live gateway routes sat outside the policy
# even once the middleware was installed: /v1/gateway/state,
# /v1/gateway/state/persistence-model and the two p142 passthrough-mapping
# routes. Probed with auth=token and a deliberately wrong bearer token,
# GET /v1/gateway/state answered 200 and returned gateway state.
#
# NOT added here, because it is a judgement call rather than an oversight:
# /v1/chat/completions and /v1/responses (plus their schema routes). Those are
# the OpenAI-compatible surface -- the most likely thing to be exposed remotely
# -- and they are currently not covered by gateway auth either. Whether they
# should answer to this policy or carry their own is the owner's decision, so
# they are reported rather than silently locked down.
_DEFAULT_GATEWAY_PREFIXES: tuple[str, ...] = ("/gateway", "/ws", "/v1/gateway")

_ACCEPTED_HEADERS: tuple[str, ...] = ("Authorization", "X-Thomas-Gateway-Token", "X-Gateway-Token")
_ACCEPTED_QUERY_PARAMS: tuple[str, ...] = ("token", "auth", "gateway_token")

# Exempt endpoints (no secrets).
_DEFAULT_EXEMPT_PATHS: tuple[str, ...] = ("/auth/policy", "/gateway/auth/policy")


def _json_error(
    status: int,
    *,
    code: str,
    message: str,
    extra_headers: Mapping[str, str] | None = None,
) -> web.Response:
    headers: dict[str, str] = {}
    if extra_headers:
        headers.update({str(k): str(v) for k, v in extra_headers.items()})
    if status == 401:
        headers.setdefault("WWW-Authenticate", 'Bearer realm="thomas-gateway"')
    return web.json_response({"ok": False, "error": {"code": code, "message": message}}, status=status, headers=headers)


def constant_time_any_match(presented: str, valid_tokens: Sequence[str]) -> bool:
    """Constant-time compare against a list of valid tokens."""
    for tok in valid_tokens:
        if hmac.compare_digest(presented, tok):
            return True
    return False


def _normalize_mode(raw: Any) -> GatewayAuthMode:
    if raw is None:
        return "disabled"
    if not isinstance(raw, str):
        raise GatewayAuthPolicyConfigError("gateway auth mode must be a string")
    mode = raw.strip().lower()
    if mode in ("", "off", "none", "disabled", "false", "0", "no"):
        return "disabled"
    if mode in ("token", "bearer", "api_key", "apikey"):
        return "token"
    raise GatewayAuthPolicyConfigError(f"unknown gateway auth mode: {raw!r}")


def _normalize_scope(raw: Any) -> GatewayAuthScope:
    if raw is None:
        return "auto"
    if not isinstance(raw, str):
        raise GatewayAuthPolicyConfigError("gateway auth scope must be a string")
    scope = raw.strip().lower()
    if scope in ("auto",):
        return "auto"
    if scope in ("prefix", "path", "paths"):
        return "prefix"
    if scope in ("all", "global"):
        return "all"
    raise GatewayAuthPolicyConfigError(f"unknown gateway auth scope: {raw!r}")


def _parse_bool(raw: Any, *, key: str) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        v = raw.strip().lower()
        if v in ("1", "true", "yes", "on"):
            return True
        if v in ("0", "false", "no", "off", ""):
            return False
    raise GatewayAuthPolicyConfigError(f"{key} must be a boolean")


def _parse_csv(raw: Any, *, key: str) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        if not all(isinstance(x, str) for x in raw):
            raise GatewayAuthPolicyConfigError(f"{key} must be a list of strings")
        return [x.strip() for x in raw if x and x.strip()]
    if isinstance(raw, str):
        items = [x.strip() for x in raw.split(",") if x.strip()]
        return items
    raise GatewayAuthPolicyConfigError(f"{key} must be a list of strings or a comma-separated string")


def _parse_int(raw: Any, *, key: str, default: int, minimum: int, maximum: int) -> int:
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise GatewayAuthPolicyConfigError(f"{key} must be an integer") from None
    if value < minimum:
        return minimum
    if value > maximum:
        return maximum
    return value


def _load_policy_dict_from_env() -> dict[str, Any] | None:
    raw = os.getenv("THOMAS_GATEWAY_AUTH_POLICY")
    if raw:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise GatewayAuthPolicyConfigError(f"THOMAS_GATEWAY_AUTH_POLICY is not valid JSON: {e}") from e
        if not isinstance(data, dict):
            raise GatewayAuthPolicyConfigError("THOMAS_GATEWAY_AUTH_POLICY must be a JSON object")
        return data

    file_path = os.getenv("THOMAS_GATEWAY_AUTH_POLICY_FILE")
    if file_path:
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError as e:
            raise GatewayAuthPolicyExternalError(f"gateway auth policy file not found: {file_path}") from e
        except OSError as e:
            raise GatewayAuthPolicyExternalError(f"failed to read gateway auth policy file: {file_path}") from e
        except json.JSONDecodeError as e:
            raise GatewayAuthPolicyConfigError(f"gateway auth policy file is not valid JSON: {e}") from e
        if not isinstance(data, dict):
            raise GatewayAuthPolicyConfigError("gateway auth policy file must contain a JSON object")
        return data

    return None


def _load_policy_dict_from_app(app: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not app:
        return None

    for key in ("gateway_auth_policy", "gateway_auth"):
        raw = app.get(key)
        if isinstance(raw, dict):
            return dict(raw)

    # Allow flat keys.
    flat: dict[str, Any] = {}
    mapping = {
        "gateway_auth_mode": "mode",
        "gateway_auth_token": "token",
        "gateway_auth_tokens": "tokens",
        "gateway_auth_scope": "scope",
        "gateway_auth_allow_query_param": "allow_query_param",
        "gateway_auth_exempt_paths": "exempt_paths",
        "gateway_auth_rate_limit_enabled": "rate_limit_enabled",
        "gateway_auth_rate_limit_max_failures": "rate_limit_max_failures",
        "gateway_auth_rate_limit_window_seconds": "rate_limit_window_seconds",
    }
    for k, outk in mapping.items():
        if k in app:
            flat[outk] = app.get(k)
    return flat or None


def load_gateway_auth_policy(app: Mapping[str, Any] | None = None) -> GatewayAuthPolicy:
    """Build policy from app config and/or environment."""
    cfg: dict[str, Any] = {}

    # Precedence: environment base then app overrides.
    env_cfg = _load_policy_dict_from_env()
    if env_cfg:
        cfg.update(env_cfg)
    app_cfg = _load_policy_dict_from_app(app)
    if app_cfg:
        cfg.update(app_cfg)

    # Convenience env vars (lowest precedence).
    cfg.setdefault("mode", os.getenv("THOMAS_GATEWAY_AUTH_MODE"))
    cfg.setdefault("scope", os.getenv("THOMAS_GATEWAY_AUTH_SCOPE"))
    if "allow_query_param" not in cfg and os.getenv("THOMAS_GATEWAY_AUTH_ALLOW_QUERY_PARAM") is not None:
        cfg["allow_query_param"] = os.getenv("THOMAS_GATEWAY_AUTH_ALLOW_QUERY_PARAM")
    if "exempt_paths" not in cfg and os.getenv("THOMAS_GATEWAY_AUTH_EXEMPT_PATHS"):
        cfg["exempt_paths"] = os.getenv("THOMAS_GATEWAY_AUTH_EXEMPT_PATHS")
    if "rate_limit_enabled" not in cfg and os.getenv("THOMAS_GATEWAY_AUTH_RATE_LIMIT_ENABLED") is not None:
        cfg["rate_limit_enabled"] = os.getenv("THOMAS_GATEWAY_AUTH_RATE_LIMIT_ENABLED")
    if "rate_limit_max_failures" not in cfg and os.getenv("THOMAS_GATEWAY_AUTH_RATE_LIMIT_MAX_FAILURES"):
        cfg["rate_limit_max_failures"] = os.getenv("THOMAS_GATEWAY_AUTH_RATE_LIMIT_MAX_FAILURES")
    if "rate_limit_window_seconds" not in cfg and os.getenv("THOMAS_GATEWAY_AUTH_RATE_LIMIT_WINDOW_SECONDS"):
        cfg["rate_limit_window_seconds"] = os.getenv("THOMAS_GATEWAY_AUTH_RATE_LIMIT_WINDOW_SECONDS")

    # Token sources
    if "tokens" not in cfg and os.getenv("THOMAS_GATEWAY_AUTH_TOKENS"):
        cfg["tokens"] = os.getenv("THOMAS_GATEWAY_AUTH_TOKENS")
    if "token" not in cfg and "tokens" not in cfg and os.getenv("THOMAS_GATEWAY_AUTH_TOKEN"):
        cfg["token"] = os.getenv("THOMAS_GATEWAY_AUTH_TOKEN")

    mode = _normalize_mode(cfg.get("mode"))
    scope = _normalize_scope(cfg.get("scope"))

    allow_query_param = cfg.get("allow_query_param")
    if allow_query_param is None:
        allow_query_param = True
    else:
        allow_query_param = _parse_bool(allow_query_param, key="allow_query_param")

    exempt_raw = cfg.get("exempt_paths")
    if exempt_raw is None:
        exempt = list(_DEFAULT_EXEMPT_PATHS)
    else:
        exempt = _parse_csv(exempt_raw, key="exempt_paths")

    rate_limit_enabled = cfg.get("rate_limit_enabled")
    if rate_limit_enabled is None:
        rate_limit_enabled = True
    else:
        rate_limit_enabled = _parse_bool(rate_limit_enabled, key="rate_limit_enabled")
    rate_limit_max_failures = _parse_int(
        cfg.get("rate_limit_max_failures"),
        key="rate_limit_max_failures",
        default=8,
        minimum=1,
        maximum=200,
    )
    rate_limit_window_seconds = _parse_int(
        cfg.get("rate_limit_window_seconds"),
        key="rate_limit_window_seconds",
        default=60,
        minimum=1,
        maximum=3600,
    )

    tokens: list[str] = []
    if "tokens" in cfg:
        tokens.extend(_parse_csv(cfg.get("tokens"), key="tokens"))
    if "token" in cfg:
        raw_token = cfg.get("token")
        if isinstance(raw_token, str):
            if raw_token.strip():
                tokens.append(raw_token.strip())
        else:
            raise GatewayAuthPolicyConfigError("token must be a string")

    # De-duplicate while preserving order.
    seen: set[str] = set()
    deduped: list[str] = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            deduped.append(t)

    return GatewayAuthPolicy(
        mode=mode,
        tokens=tuple(deduped),
        scope=scope,
        allow_query_param=allow_query_param,
        exempt_paths=tuple(exempt),
        rate_limit_enabled=bool(rate_limit_enabled),
        rate_limit_max_failures=rate_limit_max_failures,
        rate_limit_window_seconds=rate_limit_window_seconds,
    )


def _resolve_policy_cached(app: web.Application) -> GatewayAuthPolicy:
    try:
        return _POLICY_CACHE[app]
    except KeyError:
        policy = load_gateway_auth_policy(app)
        _POLICY_CACHE[app] = policy
        return policy


def _is_gateway_target_path(path: str) -> bool:
    for prefix in _DEFAULT_GATEWAY_PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
            return True
    return False


def _extract_presented_token(request: web.Request, *, allow_query_param: bool) -> str | None:
    authz = request.headers.get("Authorization")
    if authz:
        parts = authz.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            tok = parts[1].strip()
            if tok:
                return tok

    for hdr in ("X-Thomas-Gateway-Token", "X-Gateway-Token"):
        val = request.headers.get(hdr)
        if val and val.strip():
            return val.strip()

    if allow_query_param:
        q = request.rel_url.query
        for k in _ACCEPTED_QUERY_PARAMS:
            v = q.get(k)
            if v and v.strip():
                return v.strip()

    for ck in ("thomas_gateway_token", "gateway_token"):
        v = request.cookies.get(ck)
        if v and v.strip():
            return v.strip()

    return None


def _auth_failure_state_for_app(app: web.Application) -> dict[str, Any]:
    try:
        return _AUTH_FAILURES_CACHE[app]
    except KeyError:
        state: dict[str, Any] = {"__gc_at__": 0.0}
        _AUTH_FAILURES_CACHE[app] = state
        return state


def _auth_failure_lock_for_app(app: web.Application) -> asyncio.Lock:
    try:
        return _AUTH_FAILURE_LOCKS[app]
    except KeyError:
        lock = asyncio.Lock()
        _AUTH_FAILURE_LOCKS[app] = lock
        return lock


def _remote_bucket_key(request: web.Request) -> str:
    remote = str(request.remote or "").strip()
    if not remote:
        return "ip:unknown"
    try:
        return f"ip:{ipaddress.ip_address(remote).compressed}"
    except ValueError:
        return f"ip:{remote.lower()}"


def _auth_failure_bucket_keys(request: web.Request, policy: GatewayAuthPolicy) -> tuple[str, ...]:
    keys: list[str] = [_remote_bucket_key(request)]
    token = _extract_presented_token(request, allow_query_param=policy.allow_query_param)
    if token:
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
        token_key = f"token:{digest}"
        if token_key not in keys:
            keys.append(token_key)
    return tuple(keys)


async def _consume_auth_failure_rate_limit(request: web.Request, policy: GatewayAuthPolicy) -> int | None:
    if not policy.rate_limit_enabled:
        return None

    now = time.monotonic()
    cutoff = now - float(policy.rate_limit_window_seconds)
    bucket_keys = _auth_failure_bucket_keys(request, policy)
    state = _auth_failure_state_for_app(request.app)
    lock = _auth_failure_lock_for_app(request.app)

    async with lock:
        retry_after_candidates: list[int] = []
        buckets: list[deque[float]] = []
        for bucket_key in bucket_keys:
            bucket = state.get(bucket_key)
            if not isinstance(bucket, deque):
                bucket = deque()
                state[bucket_key] = bucket
            while bucket and float(bucket[0]) <= cutoff:
                bucket.popleft()
            if len(bucket) >= policy.rate_limit_max_failures:
                oldest = float(bucket[0]) if bucket else now
                retry_after = max(1, int(round(float(policy.rate_limit_window_seconds) - (now - oldest))))
                retry_after_candidates.append(retry_after)
            buckets.append(bucket)

        if retry_after_candidates:
            return max(retry_after_candidates)

        for bucket in buckets:
            bucket.append(now)

        gc_at = float(state.get("__gc_at__", 0.0) or 0.0)
        gc_interval = min(max(float(policy.rate_limit_window_seconds), 5.0), 60.0)
        if (now - gc_at) >= gc_interval:
            stale_before = now - float(policy.rate_limit_window_seconds)
            stale_keys = [
                key
                for key, value in state.items()
                if isinstance(value, deque) and (not value or float(value[-1]) <= stale_before)
            ]
            for stale_key in stale_keys:
                state.pop(stale_key, None)
            state["__gc_at__"] = now

    return None


def authorize_gateway_request(request: web.Request, policy: GatewayAuthPolicy) -> GatewayAuthDecision:
    # Do not block CORS preflight.
    if request.method.upper() == "OPTIONS":
        return GatewayAuthDecision(allowed=True)

    if not policy.required:
        return GatewayAuthDecision(allowed=True)

    path = request.path
    if path in policy.exempt_paths:
        return GatewayAuthDecision(allowed=True)

    if policy.scope in ("auto", "prefix") and not _is_gateway_target_path(path):
        return GatewayAuthDecision(allowed=True)

    if policy.mode == "token":
        if not policy.tokens:
            return GatewayAuthDecision(
                allowed=False,
                http_status=500,
                code="gateway_auth_misconfigured",
                message="gateway auth policy requires a token but none is configured",
            )

        presented = _extract_presented_token(request, allow_query_param=policy.allow_query_param)
        if not presented:
            return GatewayAuthDecision(
                allowed=False,
                http_status=401,
                code="gateway_auth_missing",
                message="missing gateway authentication token",
            )

        if not constant_time_any_match(presented, policy.tokens):
            return GatewayAuthDecision(
                allowed=False,
                http_status=401,
                code="gateway_auth_invalid",
                message="invalid gateway authentication token",
            )

        request["gateway_auth_subject"] = "token"
        return GatewayAuthDecision(allowed=True)

    return GatewayAuthDecision(
        allowed=False,
        http_status=500,
        code="gateway_auth_misconfigured",
        message="unsupported gateway auth policy mode",
    )


@web.middleware
async def gateway_auth_policy_middleware(request: web.Request, handler):
    try:
        policy = _resolve_policy_cached(request.app)
        decision = authorize_gateway_request(request, policy)
    except GatewayAuthPolicyConfigError as e:
        return _json_error(500, code="gateway_auth_config_error", message=str(e))
    except GatewayAuthPolicyExternalError as e:
        return _json_error(500, code="gateway_auth_external_error", message=str(e))

    if decision.allowed:
        return await handler(request)

    if decision.http_status in (401, 403):
        retry_after = await _consume_auth_failure_rate_limit(request, policy)
        if retry_after is not None:
            return _json_error(
                429,
                code="gateway_auth_rate_limited",
                message="too many failed gateway authentication attempts",
                extra_headers={"Retry-After": str(retry_after)},
            )

    return _json_error(
        decision.http_status,
        code=decision.code or "gateway_auth_denied",
        message=decision.message or "",
    )


def policy_to_public_info(policy: GatewayAuthPolicy) -> GatewayAuthPolicyInfo:
    return {
        "mode": policy.mode,
        "required": policy.required,
        "scope": policy.scope,
        "token_configured": bool(policy.tokens),
        "allow_query_param": policy.allow_query_param,
        "accepted_headers": list(_ACCEPTED_HEADERS),
        "accepted_query_params": list(_ACCEPTED_QUERY_PARAMS) if policy.allow_query_param else [],
        "exempt_paths": list(policy.exempt_paths),
        "rate_limit": {
            "enabled": policy.rate_limit_enabled,
            "max_failures": policy.rate_limit_max_failures,
            "window_seconds": policy.rate_limit_window_seconds,
        },
    }


routes = web.RouteTableDef()


@routes.get("/auth/policy")
@routes.get("/gateway/auth/policy")
async def get_gateway_auth_policy(request: web.Request) -> web.Response:
    """Return the currently active gateway auth policy (secrets redacted)."""
    try:
        policy = _resolve_policy_cached(request.app)
    except GatewayAuthPolicyError as e:
        return _json_error(500, code="gateway_auth_policy_unavailable", message=str(e))
    return web.json_response({"ok": True, "policy": policy_to_public_info(policy)})


# Compatibility exports for different loader styles.
ROUTES = routes
MIDDLEWARES = [gateway_auth_policy_middleware]
middlewares = MIDDLEWARES


def add_routes(app: web.Application) -> None:
    app.add_routes(routes)


def register(app: web.Application) -> None:
    """Register middleware and routes on the app (idempotent)."""
    if not app.get(_APP_REGISTERED):
        app[_APP_REGISTERED] = True
        if gateway_auth_policy_middleware not in app.middlewares:
            app.middlewares.append(gateway_auth_policy_middleware)
        add_routes(app)
