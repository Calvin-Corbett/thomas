# P051 — Nodes API routes and auth

This change adds a **Nodes HTTP API surface** (aiohttp routes) plus **bearer-token authentication**, with deterministic JSON error envelopes and a machine-readable schema for automation.

## What’s included

### Server-side (aiohttp)

Routes are defined in:

- `thomas/nodes/p051_nodes_api_routes_and_auth.py`

Register endpoints with:

```python
from aiohttp import web
from thomas.nodes import p051_nodes_api_routes_and_auth as nodes_api

app = web.Application()
nodes_api.register(app, prefix="/api")
```

Endpoints:

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/nodes` | List known nodes |
| GET | `/api/nodes/{node_id}` | Fetch a single node |
| GET | `/api/nodes/schema` | Machine-readable schema for automation |

All endpoints require auth.

## Node store integration

The API expects a node store to be available on the aiohttp application (or its root app when using subapps). The first matching key wins:

- `app["node_store"]`
- `app["nodes_store"]`
- `app["nodes"]`
- `app["node_manager"]`

If no store is configured, `/api/nodes` and `/api/nodes/{node_id}` return a deterministic `external_failure` (HTTP 502).

### Authentication

The Nodes API uses a **bearer token**.

**Client sends:**

- `Authorization: Bearer <token>`

Alternative headers are also accepted:

- `X-Thomas-Token`
- `X-Api-Key`
- `X-Auth-Token`

**Server expects a token from one of:**

- `app["nodes_api_token"]` (or `api_token`, `auth_token`, `token`)
- `app["config"]` / `app["settings"]` / `app["cfg"]` (mapping or object) with the same keys
- environment variables:
  - `THOMAS_NODES_API_TOKEN`
  - `THOMAS_API_TOKEN`

If no token is configured, requests fail deterministically:

```json
{
  "ok": false,
  "error": {
    "code": "auth_not_configured",
    "message": "Nodes API auth token is not configured.",
    "details": {
      "token_env_vars": ["THOMAS_NODES_API_TOKEN", "THOMAS_API_TOKEN"],
      "app_config_keys": ["nodes_api_token", "api_token", "auth_token", "token"]
    }
  }
}
```

## Deterministic error contracts

All API failures return:

```json
{
  "ok": false,
  "error": {
    "code": "<stable_code>",
    "message": "<stable_message>",
    "details": { }
  }
}
```

Common `code` values:

- `missing_token` (401)
- `invalid_token` (401)
- `auth_not_configured` (500)
- `invalid_input` (400)
- `external_failure` (502)
- `not_found` (404)

## CLI support

A small CLI helper is provided at:

- `thomas/cli/commands/nodes/p051_nodes_api_routes_and_auth.py`

It registers:

- `nodes api`
- `nodes api-info` (alias)

### Human output

```bash
thomas nodes api
```

### Machine-readable output

```bash
thomas nodes api --json
```

### Config check

```bash
thomas nodes api --check-config
```

This exits non-zero if neither `THOMAS_NODES_API_TOKEN` nor `THOMAS_API_TOKEN` is set.
