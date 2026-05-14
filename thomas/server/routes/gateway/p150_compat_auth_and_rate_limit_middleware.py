"""P150 - Compat auth and rate-limit middleware (Thomas-native).

This module is designed to be *imported and composed* by gateway/compat route scaffolds.
It provides:
  - Auth middleware for OpenAI-compat style routes
  - Rate limit middleware (token bucket; in-memory)
  - Deterministic, machine-readable JSON errors
  - A machine-readable status payload for automation/CLI

Key properties:
  - No global side effects on import
  - Small, testable units
  - Deterministic failures on misconfiguration

NOTE: In-memory limiting is per-process. That is typically fine for local-first Thomas.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, Optional, Tuple, TypedDict

from aiohttp import web

# ----------------------------
# Contracts
# ----------------------------

class CompatErrorDetail(TypedDict):
    code: str
    message: str


class CompatErrorResponse(TypedDict):
    ok: bool
    error: CompatErrorDetail


class CompatSecurityStatus(TypedDict):
    ok: bool
    auth: dict[str, object]
    ratelimit: dict[str, object]
    scope: dict[str, object]


@dataclass(frozen=True)
class CompatScopeConfig:
    """Where to apply compat security.

    Middlewares are global in aiohttp. This config keeps them from affecting unrelated
    routes (e.g., non-compat APIs, internal routes).

    `path_prefixes` is evaluated in-order; any matching prefix enables enforcement.
    """

    path_prefixes: tuple[str, ...] = ("/v1",)


@dataclass(frozen=True)
class CompatAuthConfig:
    """Bearer token auth for compat routes."""

    enabled: bool
    tokens: tuple[str, ...]


@dataclass(frozen=True)
class RateLimitConfig:
    """Token-bucket rate limiting."""

    enabled: bool
    rps: float
    burst: int


# ----------------------------
# Helpers
# ----------------------------

def _json_error(status: int, code: str, message: str, *, headers: dict[str, str] | None = None) -> web.Response:
    body: CompatErrorResponse = {"ok": False, "error": {"code": code, "message": message}}
    return web.json_response(body, status=status, headers=headers)


def _parse_bearer_token(value: str | None) -> str | None:
    if not value:
        return None
    parts = value.strip().split()
    if len(parts) != 2:
        return None
    scheme, token = parts[0], parts[1]
    if scheme.lower() != "bearer":
        return None
    token = token.strip()
    return token or None


def _client_key(request: web.Request) -> str:
    """Rate limit key: prefer token, else IP-ish."""
    token = _parse_bearer_token(request.headers.get("Authorization"))
    if token:
        return f"token:{token}"
    peer = request.transport.get_extra_info("peername") if request.transport else None
    if isinstance(peer, tuple) and peer:
        return f"ip:{peer[0]}"
    return "ip:unknown"


def _in_scope(request: web.Request, scope: CompatScopeConfig) -> bool:
    path = request.path or ""
    for pfx in scope.path_prefixes:
        if pfx and path.startswith(pfx):
            return True
    return False


def _truthy(v: str | None, default: bool) -> bool:
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "y", "on")


# ----------------------------
# Limiter
# ----------------------------

class TokenBucketLimiter:
    """Simple in-memory token bucket limiter.

    State is protected by a single asyncio.Lock for correctness and determinism.
    """

    def __init__(
        self,
        *,
        rps: float,
        burst: int,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        if rps <= 0:
            raise ValueError("rps must be > 0")
        if burst <= 0:
            raise ValueError("burst must be > 0")
        self._rps = float(rps)
        self._burst = int(burst)
        self._now = now
        self._lock = asyncio.Lock()
        # key -> (tokens, last_ts)
        self._state: dict[str, tuple[float, float]] = {}

    async def check(self, key: str, *, cost: float = 1.0) -> tuple[bool, float, float]:
        """Return (allowed, remaining_tokens, retry_after_seconds).

        retry_after_seconds is 0 when allowed.
        """
        if cost <= 0:
            # deterministic reject on invalid caller input
            return False, 0.0, 0.0

        async with self._lock:
            ts = float(self._now())
            tokens, last_ts = self._state.get(key, (float(self._burst), ts))

            elapsed = max(0.0, ts - last_ts)
            tokens = min(float(self._burst), tokens + elapsed * self._rps)

            if tokens >= cost:
                tokens -= cost
                self._state[key] = (tokens, ts)
                return True, tokens, 0.0

            # Not enough tokens: compute time until we have `cost` tokens.
            needed = cost - tokens
            retry_after = needed / self._rps
            self._state[key] = (tokens, ts)
            return False, tokens, retry_after


# ----------------------------
# Configuration loading
# ----------------------------

def load_compat_security_from_env() -> tuple[CompatScopeConfig, CompatAuthConfig, RateLimitConfig]:
    """Env-driven configuration (local dev + CI friendly).

    Scope:
      - THOMAS_COMPAT_PATH_PREFIXES: comma-separated (default: /v1)

    Auth:
      - THOMAS_COMPAT_AUTH_ENABLED: truthy (default: true)
      - THOMAS_COMPAT_AUTH_TOKENS: comma-separated tokens (required if enabled)

    Rate limit:
      - THOMAS_COMPAT_RATELIMIT_ENABLED: truthy (default: true)
      - THOMAS_COMPAT_RATELIMIT_RPS: float tokens/sec (default: 10)
      - THOMAS_COMPAT_RATELIMIT_BURST: int capacity (default: 20)
    """

    prefixes_raw = (os.getenv("THOMAS_COMPAT_PATH_PREFIXES") or "/v1").strip()
    prefixes = tuple(p.strip() for p in prefixes_raw.split(",") if p.strip())
    scope = CompatScopeConfig(path_prefixes=prefixes or ("/v1",))

    auth_enabled = _truthy(os.getenv("THOMAS_COMPAT_AUTH_ENABLED"), True)
    tokens_raw = (os.getenv("THOMAS_COMPAT_AUTH_TOKENS") or "").strip()
    tokens = tuple(t.strip() for t in tokens_raw.split(",") if t.strip())
    auth_cfg = CompatAuthConfig(enabled=auth_enabled, tokens=tokens)

    rl_enabled = _truthy(os.getenv("THOMAS_COMPAT_RATELIMIT_ENABLED"), True)
    rps_raw = (os.getenv("THOMAS_COMPAT_RATELIMIT_RPS") or "10").strip()
    burst_raw = (os.getenv("THOMAS_COMPAT_RATELIMIT_BURST") or "20").strip()

    try:
        rps = float(rps_raw)
    except Exception:
        rps = -1.0

    try:
        burst = int(burst_raw)
    except Exception:
        burst = -1

    if not rl_enabled:
        rl_cfg = RateLimitConfig(enabled=False, rps=10.0, burst=20)
    else:
        rl_cfg = RateLimitConfig(enabled=True, rps=rps, burst=burst)

    return scope, auth_cfg, rl_cfg


# ----------------------------
# Middlewares
# ----------------------------

def build_compat_middlewares(
    *,
    scope: CompatScopeConfig,
    auth: CompatAuthConfig,
    ratelimit: RateLimitConfig,
    limiter: TokenBucketLimiter | None = None,
) -> tuple[web.middleware, web.middleware]:
    """Factory returning (auth_middleware, ratelimit_middleware)."""

    # Validate and/or construct limiter up-front when possible.
    constructed_limiter: TokenBucketLimiter | None = limiter
    if ratelimit.enabled and constructed_limiter is None and ratelimit.rps > 0 and ratelimit.burst > 0:
        constructed_limiter = TokenBucketLimiter(rps=ratelimit.rps, burst=ratelimit.burst)

    def _ratelimit_headers(remaining: float, retry_after: float) -> dict[str, str]:
        # Remaining is float; serialize as an int floor for simplicity.
        rem_i = max(0, int(remaining))
        headers: dict[str, str] = {
            "X-RateLimit-Limit": str(int(ratelimit.burst) if ratelimit.burst > 0 else 0),
            "X-RateLimit-Remaining": str(rem_i),
        }
        if retry_after > 0:
            # RFC-ish: Retry-After in seconds, integer.
            headers["Retry-After"] = str(max(1, int(retry_after + 0.999)))
        return headers

    @web.middleware
    async def compat_auth_middleware(
        request: web.Request, handler: Callable[[web.Request], Awaitable[web.StreamResponse]]
    ) -> web.StreamResponse:
        if not _in_scope(request, scope):
            return await handler(request)

        if not auth.enabled:
            return await handler(request)

        if not auth.tokens:
            return _json_error(
                500,
                "compat_auth_not_configured",
                "Compat auth is enabled but no tokens are configured.",
            )

        token = _parse_bearer_token(request.headers.get("Authorization"))
        if not token:
            return _json_error(401, "missing_bearer_token", "Missing Authorization: Bearer <token> header.")

        if token not in auth.tokens:
            return _json_error(401, "invalid_bearer_token", "Invalid bearer token.")

        return await handler(request)

    @web.middleware
    async def compat_rate_limit_middleware(
        request: web.Request, handler: Callable[[web.Request], Awaitable[web.StreamResponse]]
    ) -> web.StreamResponse:
        if not _in_scope(request, scope):
            return await handler(request)

        if not ratelimit.enabled:
            return await handler(request)

        if ratelimit.rps <= 0 or ratelimit.burst <= 0:
            return _json_error(
                500,
                "compat_ratelimit_not_configured",
                "Compat rate limiting is enabled but rps/burst are invalid.",
            )

        if constructed_limiter is None:
            return _json_error(
                500,
                "compat_ratelimit_not_initialized",
                "Compat rate limiting is enabled but limiter is not initialized.",
            )

        key = _client_key(request)
        allowed, remaining, retry_after = await constructed_limiter.check(key, cost=1.0)
        headers = _ratelimit_headers(remaining, retry_after)

        if not allowed:
            return _json_error(429, "rate_limited", "Too many requests.", headers=headers)

        resp = await handler(request)
        # On success, attach rate-limit headers (if response supports it).
        if isinstance(resp, web.StreamResponse):
            for k, v in headers.items():
                # Don't stomp a handler's explicit header.
                if k not in resp.headers:
                    resp.headers[k] = v
        return resp

    return compat_auth_middleware, compat_rate_limit_middleware


def compat_security_status_json(
    scope: CompatScopeConfig,
    auth: CompatAuthConfig,
    ratelimit: RateLimitConfig,
) -> CompatSecurityStatus:
    """Machine-readable status for automation / CLI `--json`."""
    return {
        "ok": True,
        "scope": {"path_prefixes": list(scope.path_prefixes)},
        "auth": {"enabled": bool(auth.enabled), "tokens_configured": int(len(auth.tokens))},
        "ratelimit": {
            "enabled": bool(ratelimit.enabled),
            "rps": float(ratelimit.rps),
            "burst": int(ratelimit.burst),
        },
    }
