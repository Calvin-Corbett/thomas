# P122 - Plugin lifecycle commands (runtime-backed)

This adds **runtime-backed** plugin lifecycle commands to the Thomas CLI.

Unlike config-only plugin toggles, these commands query (and mutate) the state of
plugins in a **running Thomas runtime** via its gateway API.

## CLI surface

Commands live under the `plugins` command group:

- `thomas plugins list`
- `thomas plugins status <plugin>`
- `thomas plugins start <plugin>`
- `thomas plugins stop <plugin>`
- `thomas plugins restart <plugin>`

All commands support `--json` for machine-readable output.

## Runtime endpoint discovery

The CLI locates the runtime gateway URL using the following priority:

1. `--gateway-url`
2. Environment variables (first match):
   - `THOMAS_GATEWAY_URL`
   - `THOMAS_RUNTIME_URL`
   - `THOMAS_API_URL`
   - `THOMAS_URL`
3. `--config` (JSON or TOML), using one of the keys:
   - `gateway_url`, `runtime_url`, `api_url`, or `url` (top-level or nested under `gateway`/`runtime`/`api`)

If no gateway URL is found, commands fail deterministically with error code
`missing_runtime_config`.

## Examples

### List plugins

```bash
thomas plugins list
```

Machine-readable:

```bash
thomas plugins list --json
```

### Start a plugin

```bash
thomas plugins start filesystem --json
```

### Stop a plugin

```bash
thomas plugins stop filesystem --json
```

### Check status

```bash
thomas plugins status filesystem
```

## Error contracts

When `--json` is provided, failures always return JSON of the shape:

```json
{
  "ok": false,
  "action": "start",
  "plugin": "filesystem",
  "error": {
    "code": "runtime_unavailable",
    "message": "Unable to reach plugin runtime gateway",
    "details": {
      "url": "http://127.0.0.1:8080/plugins/filesystem/start"
    }
  }
}
```
