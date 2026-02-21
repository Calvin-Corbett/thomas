# P126 - Gateway start command

This adds a Thomas-native **gateway start** capability in both:

- **Server**: `POST /v1/gateway/start`
- **CLI**: `thomas gateway start --config <path> [--json]`

The gateway is started as a subprocess described by a small config file (JSON or TOML).

## Server API

### Endpoint

`POST /v1/gateway/start`

### Request body

```json
{
  "config_path": "/abs/or/relative/path/to/gateway.json",
  "force_restart": false
}
```

- `config_path` *(string, optional)*: config file path. If omitted, `THOMAS_GATEWAY_CONFIG` is used.
- `force_restart` *(boolean, optional)*: if a gateway subprocess is already running, restart it.

### Success response

```json
{
  "ok": true,
  "status": "started",
  "pid": 12345,
  "config_path": "/path/to/gateway.json",
  "command": ["python", "-m", "some_gateway"]
}
```

`status` is `"already_running"` when the gateway subprocess is already running.

### Error response

```json
{
  "ok": false,
  "error": {
    "type": "missing_config",
    "message": "Missing gateway config file.",
    "details": { "config_path": "/path/to/nope.json" }
  }
}
```

Error `type` values:

- `invalid_input`
- `missing_config`
- `external_failure`

## CLI

### Usage

```bash
thomas gateway start --config ./gateway.json
thomas gateway start --config ./gateway.json --json
```

### JSON output mode

When `--json` is provided, the CLI prints the same machine-readable payload as the server endpoint and exits with:

- exit code `0` on success (`ok: true`)
- exit code `1` on failure (`ok: false`)

## Config file format

Minimal JSON:

```json
{
  "command": ["python", "-c", "import time; time.sleep(3600)"]
}
```

Optional fields:

- `cwd` *(string)*: working directory for the subprocess
- `env` *(object)*: string-to-string environment variables for the subprocess

TOML supports the same structure at top-level, or under `[gateway]`.
