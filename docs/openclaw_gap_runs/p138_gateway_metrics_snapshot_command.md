# Gateway metrics snapshot command (P138)

This adds a **Gateway metrics snapshot** capability to Thomas: an automation-friendly endpoint and CLI command that returns a point-in-time JSON snapshot of gateway metrics.

Design goals:
- **Machine-readable** (`--json` on CLI; JSON response on the route)
- **Deterministic failure envelopes** (stable `error.code` values)
- **Flexible metrics sourcing** (in-process hook, gateway client, or external endpoint)

## CLI usage

```bash
thomas gateway-metrics-snapshot [--window-seconds N] [--reset] [--json]
```

Examples:

```bash
# Human-readable
thomas gateway-metrics-snapshot

# JSON for automation
thomas gateway-metrics-snapshot --json

# Request a 60s windowed snapshot (if supported by the provider)
thomas gateway-metrics-snapshot --window-seconds 60 --json

# Ask provider to reset counters after snapshot (if supported)
thomas gateway-metrics-snapshot --reset --json
```

Exit codes:
- `0` when `ok=true`
- `1` when `ok=false`

## Server route

Routes (both supported):

- `GET  /v1/gateway/metrics/snapshot`
- `POST /v1/gateway/metrics/snapshot`

Convenience aliases:
- `GET  /gateway/metrics/snapshot`
- `POST /gateway/metrics/snapshot`

### Request contract

POST JSON:

```json
{
  "reset": false,
  "window_seconds": 60
}
```

GET query params:
- `reset`: boolean-ish (`true/false/1/0/yes/no`)
- `window_seconds`: integer (1–86400)

### Success response contract

```json
{
  "ok": true,
  "taken_at": "2026-02-20T20:00:00+00:00",
  "source": "external:https://gateway.example.com/metrics/snapshot",
  "request": {
    "reset": false,
    "window_seconds": 60
  },
  "snapshot": {
    "requests_total": 123,
    "errors_total": 4
  }
}
```

### Failure response contract

```json
{
  "ok": false,
  "error": {
    "code": "missing_config",
    "message": "No gateway metrics source is configured.",
    "details": {
      "hint": "Set app['config']['gateway_metrics_url'] (or THOMAS_GATEWAY_METRICS_URL) to a reachable endpoint."
    }
  }
}
```

## Metrics source resolution order

The route attempts these sources in order:

1. **In-process hook**: `app[SNAPSHOTTER_APP_KEY]` or `app["gateway_metrics_snapshotter"]` callable returning a mapping.
2. **Gateway client object**: `app["gateway_client"]` (or `app["gateway"]` / `app["gateway_api"]`) with a method like:
   - `metrics_snapshot(reset=..., window_seconds=...)`
3. **External endpoint** configured via:
   - `app["config"]["gateway_metrics_url"]`, or
   - `THOMAS_GATEWAY_METRICS_URL`, or
   - `app["config"]["gateway_url"]` plus `/metrics/snapshot`

This keeps the command useful across gateway implementations without forcing a single internal metrics system.
