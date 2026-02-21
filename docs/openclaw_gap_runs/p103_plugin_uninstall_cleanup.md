# P103 - Plugin uninstall cleanup

## What this run does

Thomas installs plugins into a state directory under an `extensions/` root. In some
workflows (or after an interrupted uninstall), the plugin may be removed from
configuration but still have leftover files on disk.

This run performs a **safe, idempotent cleanup** of those on-disk artifacts:

- Target: `<state_dir>/extensions/<plugin_id>`
- If the target doesn't exist, the run reports `status=not_found` and exits successfully.

The implementation guards against path traversal and refuses to remove anything
outside the configured `extensions` root.

## Interfaces

### Python API

- Module: `thomas.plugins.p103_plugin_uninstall_cleanup`
- Entry: `run_plugin_uninstall_cleanup(request)`

Contracts:

- Input: `PluginUninstallCleanupRequest` (dataclass)
- Output: `PluginUninstallCleanupResult` (dataclass)

### CLI

Command module:

- `thomas.cli.commands.plugins.p103_plugin_uninstall_cleanup`

Examples:

```bash
# Remove plugin install files (human output)
thomas plugins uninstall-cleanup my-plugin

# Dry-run
thomas plugins uninstall-cleanup my-plugin --dry-run

# Machine-readable output
thomas plugins uninstall-cleanup my-plugin --json
```

## Machine-readable output

When `--json` is used, the command prints a single JSON object.

Success:

```json
{
  "ok": true,
  "result": {
    "plugin_id": "my-plugin",
    "status": "removed",
    "removed": ["..."],
    "pruned_empty_dirs": []
  }
}
```

Failure:

```json
{
  "ok": false,
  "error": {
    "code": "missing_config",
    "message": "Thomas config file not found",
    "details": { "config_path": "..." }
  }
}
```
