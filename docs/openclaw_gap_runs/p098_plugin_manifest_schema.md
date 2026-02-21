# P098 - Plugin manifest schema

This run adds a **Thomas-native** JSON Schema describing the on-disk *plugin
manifest* format.

## Why this exists

Plugin metadata becomes much easier to consume when it is **declarative** and can
be validated by tooling (editors, CI, build scripts). A JSON Schema provides:

- autocompletion and inline validation in modern editors
- a stable, machine-readable contract for automation

## CLI

A new CLI command is available under the `plugins` command group:

```bash
thomas plugins plugin-manifest-schema
```

### Machine-readable output

For automation, use `--json` to emit compact JSON to stdout:

```bash
thomas plugins plugin-manifest-schema --json > plugin_manifest.schema.json
```

### Options

- `--schema-version` (default: `v1`)
- `--draft` (default: `2020-12`, also supports `7`)
- `--include-examples` (include example manifests in the schema)

## Tool registry integration

The schema generator is also exposed as a registry-friendly callable
(`register(...)`) so it can be surfaced as a tool in environments that load
Thomas plugins.
