# P108: Plugin hook runner core

This document describes the **Thomas-native** plugin hook runner introduced in
Prompt Pack **P108**.

## What it does

The hook runner is a small core utility for:

- validating a hook execution request,
- discovering plugins (via explicit instances, a plugin manager, or a JSON
  config file),
- dispatching a named hook across plugins in a deterministic order,
- returning structured results (including per-plugin errors),
- supporting machine-readable output for automation.

Core implementation:

- `thomas/plugins/p108_plugin_hook_runner_core.py`

CLI wrapper:

- `thomas/cli/commands/plugins/p108_plugin_hook_runner_core.py`

## CLI usage

Run a hook across plugins defined in a JSON config:

```bash
thomas plugins run-hook demo --payload '{"x": 123}' --config thomas_plugins.json
```

Machine-readable output:

```bash
thomas plugins run-hook demo --payload '{"x": 123}' --config thomas_plugins.json --json
```

Print JSON schemas:

```bash
thomas plugins hook-schema --json
```

## Config file format

The runner accepts a simple JSON format:

```json
{
  "plugins": [
    "my_plugins.example:ExamplePlugin",
    {"path": "my_plugins.other:OtherPlugin", "init": {"mode": "fast"}}
  ]
}
```

Each entry in `plugins` may be:

- a string in the form `module:attribute` or `module.attribute`, referencing a
  class (instantiated with no args) or a factory function,
- an object with a `path`/`factory`/`plugin` field, plus optional `init` kwargs.

## Error model

Request/config failures raise a deterministic `HookRunnerError` with a stable
`code`.

Per-plugin hook failures are returned as `results[*].error` entries with a
stable `code` (for example, `hook_failed`).
