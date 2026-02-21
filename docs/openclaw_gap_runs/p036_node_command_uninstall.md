# P036 - Node command uninstall

## Summary

Adds a **Thomas-native** capability: **nodes command uninstall**.

It uninstalls a single npm package either:

- **Locally** (from a Node project) — Thomas searches upward from `--project-dir` until it finds a `package.json`, then runs `npm uninstall` in that directory.
- **Globally** — runs `npm uninstall -g`.

Machine-readable output is supported via `--json`, and the core module exposes JSON Schemas for automation / HTTP routes.

## CLI usage

```bash
# Uninstall a project dependency (searches for package.json upward from the given directory)
thomas nodes command uninstall lodash --project-dir ./my-app

# Uninstall a globally installed package (often used for CLI tools)
thomas nodes command uninstall eslint --global

# Dry run
thomas nodes command uninstall lodash --project-dir ./my-app --dry-run

# Machine-readable output
thomas nodes command uninstall lodash --project-dir ./my-app --json

# Use a custom npm executable (e.g. npm.cmd on Windows, or a wrapper script)
thomas nodes command uninstall lodash --npm npm
```

## Contracts

### Request (`NodeCommandUninstallRequest`)

- `package` (string, required): single npm package spec
- `project_dir` (string, default `.`): starting directory for local uninstalls (searched upward for `package.json`)
- `global_install` (bool, default `false`): uninstall globally
- `dry_run` (bool, default `false`): add `--dry-run`
- `npm_executable` (string, default `npm`)
- `timeout_s` (int | null, default `300`)

### Result (`NodeCommandUninstallResult`)

- `package`
- `command` (array of strings)
- `project_dir` (string | null)
- `global_install`
- `dry_run`
- `return_code`
- `stdout`
- `stderr`

JSON Schemas are available as:

- `NODE_COMMAND_UNINSTALL_REQUEST_SCHEMA` / `NODE_COMMAND_UNINSTALL_RESULT_SCHEMA`
- `REQUEST_SCHEMA` / `RESPONSE_SCHEMA`
- `JSON_INPUT_SCHEMA` / `JSON_OUTPUT_SCHEMA`

## Deterministic errors

The core API raises `NodeCommandUninstallError` with stable `code` values:

- `invalid_input`: malformed request values
- `missing_config`: local uninstall requested but `package.json` not found (searched upward)
- `npm_not_found`: npm executable not available
- `external_timeout`: npm process exceeded timeout
- `uninstall_failed`: npm returned a non-zero exit code
- `external_failure`: unexpected subprocess invocation error

## Tests

- `tests/prompt_pack/test_p036_node_command_uninstall.py`
  - local uninstall success
  - global uninstall success
  - missing `package.json` failure
  - invalid package spec failure
  - missing npm failure
  - npm non-zero exit code failure
  - CLI `--json` success/failure behavior
