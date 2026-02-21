# P135 — Gateway state persistence model

This change adds a **Thomas-native gateway state persistence** layer.

It’s intentionally small and boring (in the good way): deterministic errors, typed contracts, and safe file writes.

## Server routes (aiohttp)

- `GET /v1/gateway/state/persistence-model`
  - Returns the active persistence model and size limits.

- `POST /v1/gateway/state/persistence-model`
  - Sets the persistence model.
  - `mode: "memory" | "file"`
  - In `file` mode, persisted under `<state_dir>/gateway/gateway_state.json`
  - `state_dir` can be provided in the request or via `THOMAS_STATE_DIR`.

- `GET /v1/gateway/state`
  - Returns the current gateway state snapshot.
  - Includes headers:
    - `ETag: W/"<version>"`
    - `X-Thomas-Gateway-State-Version: <version>`

- `PUT /v1/gateway/state`
  - Replaces the current gateway state.
  - Optional optimistic concurrency:
    - request body `expected_version`
    - or `If-Match: W/"<version>"`

All responses are JSON and include deterministic error payloads on failure.

## Contracts

### Persistence model request

```json
{
  "mode": "memory | file",
  "state_dir": "/path/base/dir",
  "max_state_bytes": 262144
}
```

### Persistence model response

```json
{
  "schema_version": 1,
  "mode": "memory",
  "state_dir": null,
  "state_file": null,
  "max_state_bytes": 262144
}
```

### Set state request

```json
{
  "state": { "any": "json object" },
  "expected_version": 3
}
```

### Gateway state response

```json
{
  "schema_version": 1,
  "version": 4,
  "updated_at": 1730000000.123,
  "state": { "any": "json object" }
}
```

## Error behavior

Errors are deterministic and machine-readable:

```json
{
  "error": {
    "code": "version_conflict",
    "message": "expected_version 3 does not match current version 4"
  }
}
```

Common error codes:
- `invalid_json`
- `invalid_request`
- `invalid_mode`
- `missing_config`
- `state_too_large`
- `version_conflict`
- `io_error`
- `invalid_state_file`
- `unsupported_schema`
