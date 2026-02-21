# P102 - Install plugin from local path

This adds **local-path plugin installation** to Thomas.

## What it does

Given a directory on disk that represents a plugin project, the installer:

1. Validates the path and derives a plugin name (or uses `--name`).
2. Copies the plugin directory into Thomas' managed plugins directory.
3. Writes/updates a machine-readable `installed_plugins.json` manifest.

The install is staged into a temporary directory and then moved into place, so
partially-copied plugins are avoided on failure.

## CLI

```bash
thomas plugins install-from-local-path ./path/to/plugin
```

### Options

- `--name TEXT` – override the plugin name.
- `--install-root PATH` – override the install root directory.
- `--overwrite` – replace any existing installation.
- `--json` – emit machine-readable JSON.

### JSON output

Success:

```json
{"ok": true, "plugin_name": "demo_plugin", "installed_path": "..."}
```

Failure:

```json
{"ok": false, "error": {"code": "missing_plugin_config", "message": "...", "details": {...}}}
```

## Deterministic errors

- `invalid_input` – invalid automation payload.
- `invalid_path` – source path does not exist.
- `not_a_directory` – source path is not a directory.
- `missing_plugin_config` – no recognizable plugin metadata found.
- `already_installed` – destination exists and `--overwrite` was not provided.
- `copy_failed` – filesystem copy failed.
- `move_failed` – filesystem move failed.
- `write_failed` – writing the manifest failed.
