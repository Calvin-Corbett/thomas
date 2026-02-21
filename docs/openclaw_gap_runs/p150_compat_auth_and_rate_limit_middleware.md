# P150 — Compat auth and rate-limit middleware

## What this adds

Thomas-native middleware that can be applied to “compat” HTTP routes (OpenAI-like endpoints in the gateway layer):

- **Auth middleware**
  - Requires `Authorization: Bearer <token>`
  - Deterministic, JSON error responses
  - Scope-controlled via path prefixes (so it won’t hit unrelated routes)
- **Rate-limit middleware**
  - In-memory token bucket, keyed by bearer token when present, otherwise best-effort IP
  - Emits `X-RateLimit-*` headers on success and `Retry-After` on 429
  - Deterministic, JSON error responses
- **Machine-readable config status**
  - `compat_security_status_json(...)`
  - CLI helper supports `--json`

This module is intentionally self-contained and does not modify global app wiring, so other gateway route scaffolds can import and apply it without cross-cutting edits.

## Configuration (environment variables)

Scope:
- `THOMAS_COMPAT_PATH_PREFIXES` (comma-separated; default: `/v1`)

Auth:
- `THOMAS_COMPAT_AUTH_ENABLED` (default: true)
- `THOMAS_COMPAT_AUTH_TOKENS` (comma-separated; required when enabled)

Rate limit:
- `THOMAS_COMPAT_RATELIMIT_ENABLED` (default: true)
- `THOMAS_COMPAT_RATELIMIT_RPS` (default: `10`)
- `THOMAS_COMPAT_RATELIMIT_BURST` (default: `20`)

## Error shape (JSON)

All failures are machine-readable:

```json
{
  "ok": false,
  "error": {
    "code": "rate_limited",
    "message": "Too many requests."
  }
}
```

## How to apply in a route

Typical usage:

- Load config (env or your config system)
- Build middlewares via `build_compat_middlewares(...)`
- Add them to your `aiohttp.web.Application(middlewares=[...])`

## Tests

Owned tests cover:
- Missing bearer token → 401 with deterministic error code (in-scope only)
- Valid token → 200
- Rate-limit burst exhaustion → 429 + `Retry-After`
- Machine-readable status payload
