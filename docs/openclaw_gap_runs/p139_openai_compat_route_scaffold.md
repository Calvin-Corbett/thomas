# P139 — OpenAI-compatible gateway route scaffold

This adds a **gateway** route module and a matching **CLI command** that form a minimal OpenAI-compatible proxy surface inside Thomas.

It is intentionally a scaffold:

- exposes a discoverable schema document
- provides deterministic, machine-readable errors
- proxies **Chat Completions** requests to an upstream OpenAI-compatible provider (JSON + SSE)

## Server route

Module:

- `thomas/server/routes/gateway/p139_openai_compat_route_scaffold.py`

### Paths

The module defines internal routes at:

- `/openai-compat/schema`
- `/openai-compat/health`
- `/openai-compat/v1/chat/completions`

If the Thomas server mounts gateway routes under `/gateway` (common), the external paths become:

- `/gateway/openai-compat/schema`
- `/gateway/openai-compat/health`
- `/gateway/openai-compat/v1/chat/completions`

### Configuration

The proxy needs an upstream base URL.

Config sources are checked in order:

1. `request.app["gateway_openai_compat"]` mapping
2. `request.app["config"]` / `request.app["settings"]` mapping (best-effort)
3. Environment variables

Environment variables:

- `THOMAS_GATEWAY_OPENAI_BASE_URL` (required)
- `THOMAS_GATEWAY_OPENAI_API_KEY` (required unless allow-no-key is enabled, or the client supplies `Authorization: Bearer …`)
- `THOMAS_GATEWAY_OPENAI_TIMEOUT_S` (optional; default `30`)
- `THOMAS_GATEWAY_OPENAI_ALLOW_NO_KEY` (optional; set to `1`/`true` to allow unauthenticated upstreams)

### Error format

All deterministic failures use an OpenAI-compatible envelope:

```json
{
  "error": {
    "message": "...",
    "type": "invalid_request_error | configuration_error | upstream_error",
    "param": null,
    "code": "thomas_..."
  }
}
```

## CLI command

Module:

- `thomas/cli/commands/gateway/p139_openai_compat_route_scaffold.py`

Purpose:

- prints the schema document for automation (`--json`)
- optionally includes env-derived config values (`--with-config`)

Example:

```bash
thomas gateway p139-openai-compat-route-scaffold --json
```
