# P144 — Responses compatibility route scaffold

This adds an OpenAI-style **Responses API** compatibility surface to Thomas, implemented as a **gateway route scaffold**.

## Added modules

- `thomas/server/routes/gateway/p144_responses_compat_route_scaffold.py`
  - `POST /v1/responses` — create a response (stub or proxy mode)
  - `GET /v1/responses/schema` — machine-readable JSON schema for automation

- `thomas/cli/commands/gateway/p144_responses_compat_route_scaffold.py`
  - Emits the same schema/metadata.
  - Supports `--json` for automation pipelines.

## Modes

- **stub**: deterministic local echo response (no upstream required)
- **proxy**: forwards requests to `{UPSTREAM}/v1/responses`
- **auto** (default): proxy only if an upstream base URL is configured; otherwise stub

Mode env var:

- `THOMAS_RESPONSES_COMPAT_MODE=auto|stub|proxy`

Upstream base URL:

- `THOMAS_RESPONSES_COMPAT_UPSTREAM_BASE_URL=http://host:port`

Shared gateway fallback env vars (checked if the above is not set):

- `THOMAS_GATEWAY_UPSTREAM_BASE_URL`
- `THOMAS_UPSTREAM_BASE_URL`
- `OPENAI_BASE_URL`
- `OPENAI_API_BASE`

Timeout:

- `THOMAS_RESPONSES_COMPAT_TIMEOUT_S` (default: 30 seconds)

## Error contract

Errors use an OpenAI-style envelope:

```json
{
  "error": {
    "message": "Missing required field: model",
    "type": "invalid_request_error",
    "param": "model",
    "code": "missing_field"
  }
}
```

Deterministic error codes are returned for:

- invalid JSON (`invalid_json`)
- invalid request payloads (`missing_field`, `invalid_field`, `invalid_input_item`)
- missing proxy configuration (`missing_config`)
- upstream failures (`upstream_request_failed`, `upstream_non_json`, `upstream_invalid_json`, `upstream_http_error`)
