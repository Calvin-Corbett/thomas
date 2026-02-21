# P105 — Plugin registry core model

This run introduces a **Thomas-native plugin registry model**: a stable,
machine-readable representation of plugins and (optionally) the tools they
expose.

## What shipped

- **Core model + builder**: `thomas/plugins/p105_plugin_registry_core_model.py`
  - Typed request/response contracts (`BuildPluginRegistryRequest`,
    `PluginRegistryModel`, etc.)
  - Deterministic error objects (`code`, `message`, `details`)
  - Defensive discovery (explicit module list, or package scan of
    `thomas.plugins`)
  - A tool-style callable: `plugins_registry_model(payload)` returning
    `{ok: bool, result|error: ...}`

- **CLI command**: `thomas plugins registry-model`
  - Human output by default
  - `--json` for automation-friendly output

## CLI usage

```bash
# Human output
thomas plugins registry-model

# Machine-readable JSON
thomas plugins registry-model --json

# Restrict to explicit modules
thomas plugins registry-model --plugin thomas.plugins.some_plugin --plugin thomas.plugins.other

# Exclude tool metadata
thomas plugins registry-model --no-tools
```

## Output shape

In `--json` mode, the CLI emits:

```json
{
  "ok": true,
  "result": {
    "schema_version": "1.0",
    "plugins": [
      {
        "name": "...",
        "module": "...",
        "version": "...",
        "description": "...",
        "tools": [
          {
            "name": "...",
            "description": "...",
            "input_schema": {},
            "output_schema": {}
          }
        ],
        "load_error": {
          "code": "PLUGIN_IMPORT_FAILED",
          "message": "...",
          "details": {"module": "...", "exception": "ImportError"}
        }
      }
    ]
  }
}
```

## Notes

- The model is intentionally conservative: it avoids timestamps and other
  non-deterministic fields so automation diffs cleanly.
- When a plugin fails to import, the failure can be captured as a structured
  `load_error` entry (or forced to raise via `on_error="raise"`).
