# P133 — Gateway health detailed payload

## What this adds

A Thomas-native way to fetch a **detailed health snapshot** from a running Gateway.

Two entrypoints are provided:

- **Server route** (aiohttp): `GET|POST /gateway/health/detailed`
- **CLI command**: `gateway-health-detailed-payload`

The feature is intentionally **machine-friendly**: JSON output is stable and errors are deterministic.

## Configuration

By default (no explicit `--url` / no `url` override), the probe resolves Gateway settings from:

- `THOMAS_GATEWAY_URL` (required)
- `THOMAS_GATEWAY_TOKEN` (optional)
- `THOMAS_GATEWAY_PASSWORD` (optional)

If both token and password are present, token is preferred deterministically.

If `--url` is provided, it overrides the URL but **auth may still be resolved from env/config** unless explicitly overridden.

## CLI

### Examples

```bash
# Uses env/config (THOMAS_GATEWAY_URL, THOMAS_GATEWAY_TOKEN/PASSWORD)
thomas gateway-health-detailed-payload --json

# Explicit URL + explicit auth
thomas gateway-health-detailed-payload --url ws://127.0.0.1:18789 --token $TOKEN --json
```

### Output (success)

```json
{
  "ok": true,
  "schema_version": 1,
  "service": { "name": "thomas", "version": "0", "platform": "...", "python": "...", "pid": 1234 },
  "gateway": { "url": "ws://127.0.0.1:18789", "protocol": 3 },
  "duration_ms": 42,
  "snapshot": { "...": "Gateway-provided payload" }
}
```

### Output (error)

```json
{
  "ok": false,
  "schema_version": 1,
  "error": {
    "type": "invalid_request|configuration_error|gateway_error",
    "code": "…",
    "message": "…",
    "details": { "…": "…" }
  }
}
```

## Server route

### Endpoint

`GET|POST /gateway/health/detailed`

### Inputs

- Query params **or** JSON body:
  - `url` (optional)
  - `token` (optional)
  - `password` (optional)
  - `timeout_ms` (optional, default 10000)

Query params override body fields (deterministic override semantics).

### Responses

Same JSON schema as CLI (`ok: true|false` with either a `snapshot` or `error`).

## Notes / non-goals

- This is a *minimal* WebSocket RPC client: it performs `connect` and then calls `health`.
- It does not implement pairing flows, device-token persistence, or other admin methods.
- A best-effort device claim is included only when a `connect.challenge` is observed.
