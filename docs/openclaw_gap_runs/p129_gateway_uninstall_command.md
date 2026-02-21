# P129 — Gateway uninstall command

This GAP run adds a **Thomas-native** Gateway uninstall surface:

- **Server route** (aiohttp): `POST /v1/gateway/uninstall` (also accepts `/gateway/uninstall`)
- **CLI command**: `thomas gateway uninstall ...`

The implementation is deliberately conservative and automation-friendly:

- It removes only the Gateway footprint inside the **Thomas state directory**.
- It emits **deterministic** machine-readable errors (stable `code` values).
- It supports a `--json` output mode for automation.
- It is **idempotent**: if the Gateway footprint is missing, uninstall succeeds with `already_absent=true`.

---

## HTTP API

### Endpoint

`POST /v1/gateway/uninstall`  
(compat alias: `POST /gateway/uninstall`)

### Request JSON

```json
{
  "state_dir": "/path/to/state",
  "dry_run": false,
  "purge_state": false
}
```

All fields are optional:

- `state_dir` *(string, optional)*: override the resolved state directory (useful for automation/tests).
- `dry_run` *(bool, optional)*: compute what would be removed without changing the filesystem.
- `purge_state` *(bool, optional)*: reserved for future behavior (currently equivalent to default).

### Success JSON

```json
{
  "ok": true,
  "result": {
    "uninstalled": true,
    "already_absent": false,
    "dry_run": false,
    "removed_paths": [
      "/path/to/state/gateway",
      "/path/to/state/gateway.json"
    ],
    "ran_external_uninstall": false,
    "external_uninstall_command": null
  }
}
```

If the Gateway is not present, the route still returns `200`:

```json
{
  "ok": true,
  "result": {
    "uninstalled": false,
    "already_absent": true,
    "dry_run": false,
    "removed_paths": [],
    "ran_external_uninstall": false,
    "external_uninstall_command": null
  }
}
```

### Failure JSON

```json
{
  "ok": false,
  "error": {
    "code": "invalid_request",
    "message": "..."
  }
}
```

Deterministic error codes:

- `invalid_request` (HTTP 400)
- `missing_configuration` (HTTP 409)
- `external_uninstall_failed` (HTTP 502)
- `filesystem_error` (HTTP 500)

---

## CLI

### Usage

```bash
thomas gateway uninstall
thomas gateway uninstall --dry-run
thomas gateway uninstall --state-dir /tmp/thomas-state
thomas gateway uninstall --json
```

CLI options:

- `--state-dir PATH`: override Thomas state directory.
- `--dry-run`: show what would be removed without making changes.
- `--purge-state`: reserved for future behavior.
- `--json`: emit machine-readable JSON to stdout.

On failure, the CLI exits non-zero and prints either a human-readable error or JSON.
