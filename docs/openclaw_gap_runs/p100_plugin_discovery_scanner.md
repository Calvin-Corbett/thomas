# P100 Plugin discovery scanner

This adds a **Thomas-native plugin discovery scanner** that can enumerate plugin candidates from:

- **Filesystem search paths** (explicit `--path` / `search_paths`)
- **Python entry points** (default group: `thomas.plugins`)

It exposes a machine-readable JSON mode for automation and includes deterministic error handling.

## CLI

Command name:

```bash
thomas plugins p100-plugin-discovery-scanner --path ./plugins
```

Machine-readable JSON:

```bash
thomas plugins p100-plugin-discovery-scanner --path ./plugins --json
```

Strict mode (non-zero exit when any plugin has issues):

```bash
thomas plugins p100-plugin-discovery-scanner --path ./plugins --import --strict
```

### Options

- `--path / --search-path` (repeatable): directory to scan
- `--config`: config file to read paths from when `--path` is omitted
- `--no-entry-points`: disable entry point scanning
- `--entry-point-group`: override entry point group (default `thomas.plugins`)
- `--import`: attempt to import plugin candidates to validate loadability
- `--recursive`: recurse under search paths
- `--strict`: fail if any plugin reports issues (syntax/import errors)
- `--json`: output JSON instead of human text

## Gateway-style entry point

The plugin module also provides a JSON-compatible `run(payload)` entry point for Gateway/API style execution:

- Module: `thomas.plugins.p100_plugin_discovery_scanner`
- Function: `run(payload: Mapping[str, Any]) -> dict[str, Any]`

## Input / Output contracts

### Request payload

The scanner request contract is defined by `PluginDiscoveryScanRequest` and the JSON schema constant:

- `REQUEST_JSON_SCHEMA`

Fields (JSON):

```json
{
  "search_paths": ["./plugins"],
  "config_path": null,
  "include_entry_points": true,
  "entry_point_group": "thomas.plugins",
  "import_plugins": false,
  "recursive": false
}
```

### Result payload

The scanner result contract is defined by `PluginDiscoveryScanResult` and the JSON schema constant:

- `RESULT_JSON_SCHEMA`

Example:

```json
{
  "scanned_paths": ["/abs/path/to/plugins"],
  "entry_point_group": "thomas.plugins",
  "plugins": [
    {
      "name": "example",
      "source": "filesystem",
      "module": "example",
      "file_path": "/abs/path/to/plugins/example.py",
      "distribution": null,
      "version": "1.0.0",
      "description": "Example plugin",
      "import_checked": false,
      "importable": null,
      "issues": []
    }
  ]
}
```

## Deterministic errors

Fatal errors raise `PluginDiscoveryScannerError` with stable `code` values:

- `invalid_request`
- `missing_config`
- `invalid_config`
- `path_not_found`
- `path_not_directory`

In `--json` mode, CLI errors are emitted as:

```json
{
  "ok": false,
  "error": {
    "code": "missing_config",
    "message": "Config file not found.",
    "details": { "config_path": "/path/to/config" }
  }
}
```

In strict mode, plugin-level issues (syntax/import errors) are emitted as:

```json
{
  "ok": false,
  "error": {
    "code": "plugin_load_failure",
    "message": "One or more plugins reported issues.",
    "details": {
      "issue_count": 1,
      "plugins_with_issues": [ ... ]
    }
  }
}
```

## Notes

- Metadata (`name`, `version`, `description`) is extracted without execution via AST parsing when possible.
- When `--import` is used, candidates are imported under a synthetic module name to reduce collisions.
- For package candidates, the import check treats the directory as a package to improve relative-import compatibility.
