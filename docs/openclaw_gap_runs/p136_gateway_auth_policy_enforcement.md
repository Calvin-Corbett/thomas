# P136 - Gateway auth policy enforcement

This adds a **gateway authentication policy** layer and enforces it via aiohttp middleware.

Goal: if you configure gateway auth, the gateway stops accepting unauthenticated requests in a **deterministic, automation-friendly** way.

## Configuration

### Quick env vars

- `THOMAS_GATEWAY_AUTH_MODE`
  - `disabled` (default)
  - `token` (require a token)
- `THOMAS_GATEWAY_AUTH_TOKEN`
  - Token value (required when mode is `token`), single token
- `THOMAS_GATEWAY_AUTH_TOKENS`
  - Comma-separated list of tokens (optional alternative to `..._TOKEN`)
- `THOMAS_GATEWAY_AUTH_SCOPE`
  - `auto` (default): enforce only for gateway-like paths (`/gateway/*`, `/ws*`)
  - `prefix`: same as auto, but explicit
  - `all`: enforce for all non-exempt paths in the app that installed the middleware
- `THOMAS_GATEWAY_AUTH_ALLOW_QUERY_PARAM`
  - `true` (default) / `false`
- `THOMAS_GATEWAY_AUTH_EXEMPT_PATHS`
  - Comma-separated paths exempt from auth (defaults include policy endpoints)

### JSON policy schema

If you need more structure, use one of:
- `THOMAS_GATEWAY_AUTH_POLICY` (JSON string object)
- `THOMAS_GATEWAY_AUTH_POLICY_FILE` (path to JSON file)

Example:

```json
{
  "mode": "token",
  "tokens": ["a", "b"],
  "scope": "auto",
  "allow_query_param": true,
  "exempt_paths": ["/auth/policy", "/gateway/auth/policy"]
}
```

## Server behavior

Denied requests return deterministic JSON:

```json
{
  "ok": false,
  "error": {
    "code": "gateway_auth_missing",
    "message": "missing gateway authentication token"
  }
}
```

Common error codes:
- `gateway_auth_missing` (401)
- `gateway_auth_invalid` (401)
- `gateway_auth_misconfigured` (500)
- `gateway_auth_config_error` (500)
- `gateway_auth_external_error` (500)

### Introspection endpoint (machine-readable)

`GET /auth/policy` and `GET /gateway/auth/policy` return the active policy with secrets redacted:

```json
{
  "ok": true,
  "policy": {
    "mode": "token",
    "required": true,
    "scope": "auto",
    "token_configured": true,
    "allow_query_param": true,
    "accepted_headers": ["Authorization", "X-Thomas-Gateway-Token", "X-Gateway-Token"],
    "accepted_query_params": ["token", "auth", "gateway_token"],
    "exempt_paths": ["/auth/policy", "/gateway/auth/policy"]
  }
}
```

## CLI helper (`--json`)

Describe policy:

```bash
python -m thomas.cli.commands.gateway.p136_gateway_auth_policy_enforcement --describe --json
```

Evaluate a token:

```bash
python -m thomas.cli.commands.gateway.p136_gateway_auth_policy_enforcement --token "$TOKEN" --json
```

Exit codes:
- `0` allowed / success
- `2` denied
- `1` error (policy misconfigured / unreadable)

## Test commands executed

```bash
python -m pytest -q tests/prompt_pack/test_p136_gateway_auth_policy_enforcement.py
python -m pytest -q tests/test_server_access_mode.py tests/test_server_chats_api.py
```

## Risks

- Your server’s gateway prefix might not be `/gateway` or `/ws`; in that case set `THOMAS_GATEWAY_AUTH_SCOPE=all` or change your path conventions.
- Depending on how your server loads routes/middleware, you may need to call `register(app)` explicitly; the module also exports `ROUTES` and `MIDDLEWARES` for loader-style discovery.
