# P121 — Plugin list command runtime-backed

This is the Thomas implementation of **plugins list** backed by **runtime inspection**
(config + on-disk plugin payloads), with an optional machine-readable JSON output.

## What it does

1. Resolves the active config file (default: `${THOMAS_HOME}/thomas.json`, but also supports yaml/toml).
2. Reads plugin configuration from:

   - `plugins.entries` (dict keyed by id, or list of objects with `id`)
   - `plugins.installs` (dict keyed by id, or list of objects with `id`)

3. Resolves the plugins directory (default: `${config_dir}/plugins`, override via `THOMAS_PLUGINS_DIR` or `--plugins-dir`).
4. For each plugin, determines:
   - enabled/disabled (from config)
   - installed/missing (from filesystem)
   - metadata (best-effort from manifests)

Supported manifest candidates (first found wins):
- `plugin.json`
- `manifest.json`
- `package.json`
- `pyproject.toml`

## CLI usage

```bash
thomas plugins list
thomas plugins list --only-enabled
thomas plugins list --json
thomas plugins list --schema
thomas plugins list --config /path/to/thomas.json --plugins-dir /path/to/plugins
```

## JSON output contract

`--json` prints exactly one JSON object to stdout.

Success shape:

```json
{
  "ok": true,
  "config_path": "/path/to/thomas.json",
  "plugins_dir": "/path/to/plugins",
  "plugins": [
    {
      "id": "alpha",
      "enabled": true,
      "installed": true,
      "status": "ok",
      "name": "Alpha Plugin",
      "version": "2.3.4",
      "source": "local",
      "spec": "./alpha",
      "path": "/path/to/plugins/alpha",
      "error": null
    }
  ]
}
```

Failure shape:

```json
{
  "ok": false,
  "error": {
    "code": "CONFIG_MISSING",
    "message": "configuration file not found",
    "detail": "/path/to/thomas.json"
  }
}
```

The JSON schema is embedded as:
- `thomas.plugins.p121_plugin_list_command_runtime_backed.PLUGIN_LIST_JSON_SCHEMA`

`--schema` prints that schema to stdout.

## Error codes

- `INVALID_INPUT` — invalid config path type (e.g. directory).
- `CONFIG_MISSING` — config file not found.
- `CONFIG_INVALID` — config file cannot be parsed / wrong root type.
- `EXTERNAL_FAILURE` — OS-level read failure.

Per-plugin manifest issues do not fail the command; they mark that plugin as:
- `status = "error"` and set `error` with the parse exception.
