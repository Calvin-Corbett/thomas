# P117 - Plugin config schema validator

This run adds a **plugin configuration validator** that checks a plugin's config
payload (JSON/YAML/TOML) against a JSON Schema.

The implementation is Thomas-native:

- Core logic lives in `thomas/plugins/p117_plugin_config_schema_validator.py`.
- A CLI command lives in `thomas/cli/commands/plugins/p117_plugin_config_schema_validator.py`.
- Output supports both human-readable text and stable `--json` mode for CI/Gateway automation.

## CLI usage

Validate a config file against an explicit schema file:

```bash
thomas plugins validate-config --config ./my_plugin_config.yaml --schema ./schema.json
```

Machine-readable output:

```bash
thomas plugins validate-config --config ./my_plugin_config.yaml --schema ./schema.json --json
```

Inline JSON for automation:

```bash
thomas plugins validate-config \
  --config-json '{"enabled": true}' \
  --schema-json '{"type":"object","properties":{"enabled":{"type":"boolean"}},"required":["enabled"]}' \
  --json
```

Emit the JSON schema for the `--json` output envelope:

```bash
thomas plugins validate-config --output-schema
```

## Output contract (`--json`)

### Success envelope

```json
{
  "ok": true,
  "result": {
    "plugin": "example_plugin",
    "valid": true,
    "schema_source": "inline",
    "issues": []
  }
}
```

### Fatal error envelope

```json
{
  "ok": false,
  "error": {
    "code": "CONFIG_NOT_FOUND",
    "message": "Config file not found.",
    "details": {
      "path": "./missing.json",
      "kind": "config"
    }
  }
}
```

## Exit codes

- `0` - Config validates against schema
- `2` - Config does **not** validate against schema
- `1` - Fatal error (missing config, parse error, schema discovery failure, etc.)
