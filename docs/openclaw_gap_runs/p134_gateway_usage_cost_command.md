# P134 - Gateway usage-cost command

Adds a **Gateway usage-cost** command to Thomas.

It queries the configured Gateway service for aggregated **usage** (requests + tokens) and **cost** over a date range.

## CLI

### Human output

```bash
thomas gateway usage-cost --start-date 2026-02-01 --end-date 2026-02-20
```

### JSON output (automation)

```bash
thomas gateway usage-cost --start-date 2026-02-01 --end-date 2026-02-20 --json
```

### Configuration

Resolves Gateway credentials from:

1. CLI flags: `--gateway-url`, `--gateway-api-key`
2. Environment variables:
   - `THOMAS_GATEWAY_URL` (or `GATEWAY_URL`)
   - `THOMAS_GATEWAY_API_KEY` (or `GATEWAY_API_KEY`)

Upstream endpoint overrides (for heterogeneous deployments):

- `THOMAS_GATEWAY_USAGE_COST_PATH` (default `/usage-cost`)
- `THOMAS_GATEWAY_USAGE_COST_METHOD` (default `POST`)

## Server route

The server exposes:

- `GET /gateway/usage-cost?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD`
- `POST /gateway/usage-cost` with a JSON body:

```json
{
  "start_date": "2026-02-01",
  "end_date": "2026-02-20",
  "project": "optional",
  "model": "optional"
}
```

Successful responses are JSON:

```json
{
  "ok": true,
  "data": {
    "start_date": "2026-02-01",
    "end_date": "2026-02-20",
    "currency": "USD",
    "requests": 123,
    "input_tokens": 456,
    "output_tokens": 789,
    "total_tokens": 1245,
    "total_cost_usd": 12.34,
    "breakdown": []
  }
}
```

Errors are deterministic and machine-readable:

```json
{
  "ok": false,
  "error": {
    "code": "missing_gateway_url",
    "message": "Gateway URL is not configured (set THOMAS_GATEWAY_URL or pass --gateway-url)"
  }
}
```
