# P127 - Gateway restart command

This adds a **Thomas-native** gateway restart command with:

- an HTTP endpoint on the Thomas server
- a CLI command with optional machine-readable output (`--json`)
- a schema endpoint (`GET /gateway/restart/schema`) for automation tooling that wants a route contract

## Server API

### Endpoint

`POST /gateway/restart`

### Request body (JSON, optional)

```json
{
  "gateway": "default",
  "force": false
}
```

### Success response (JSON)

```json
{
  "ok": true,
  "gateway": "default",
  "status": "restart_requested",
  "method": "controller",
  "message": "Gateway restart requested."
}
```

### Failure response (JSON)

```json
{
  "ok": false,
  "error": {
    "code": "missing_config",
    "message": "Gateway restart is not configured.",
    "details": {}
  }
}
```

Deterministic error codes:

- `invalid_input` – body is invalid JSON / wrong shape / wrong types
- `missing_config` – no restart mechanism configured
- `external_failure` – restart mechanism raised or failed

### Schema endpoint

`GET /gateway/restart/schema` returns a JSON schema-like contract that can be used by automation.

## CLI

The CLI module supports direct invocation via `run([...])` and exposes a conservative `COMMAND_SPEC` for discovery-based CLIs.

### Usage

```bash
# Human output
python -m thomas gateway restart --server-url http://localhost:8080

# Target a specific gateway id (if supported by your integration)
python -m thomas gateway restart --server-url http://localhost:8080 --gateway default

# Machine-readable output
python -m thomas gateway restart --server-url http://localhost:8080 --json
```
