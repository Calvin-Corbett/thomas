# P037 — Nodes registry model

This gap run adds a **Thomas-native** "nodes registry model": a small, strongly validated data model that can load a registry of remote nodes from a file, URL, config mapping, or environment variables.

The goal is to make it easy for both humans and automation to ask:

> “What nodes does this Thomas instance know about?”

…and get a deterministic answer (or a deterministic error).

## Registry schema

The loader accepts a few common shapes:

### Object with `nodes`
```json
{
  "nodes": [
    { "id": "alpha", "endpoint": "http://alpha.local:8080", "labels": ["gpu", "us"] },
    { "id": "beta",  "endpoint": "beta.local:9090",         "tags": "eu,edge" }
  ]
}
```

### List form
```json
[
  { "id": "alpha", "endpoint": "http://alpha.local:8080" },
  { "id": "beta",  "endpoint": "beta.local:9090" }
]
```

### Mapping form
```json
{
  "alpha": { "endpoint": "http://alpha.local:8080" },
  "beta":  { "endpoint": "beta.local:9090", "labels": ["edge"] }
}
```

Notes:

- `endpoint` may be `http(s)://...` or `host[:port]` (which is normalized to `http://...`).
- `labels` can be a list of strings or a comma-separated string.
- Extra fields are preserved in `meta` (best-effort JSON-safe).
- Duplicate node ids are rejected deterministically.

## Configuration resolution

`load_nodes_registry()` resolves the registry source in this order:

1) Explicit `source` argument (file path, `file://...` URL, or https URL)
2) Inline config forms:
   - `config["nodes"]` as a list/dict of node entries
   - `config["nodes_registry"]` as a list/dict/`{"nodes":[...]}`
3) Config keys (permissive):
   - `nodes_registry`, `nodes_registry_path`, `nodesRegistry`, `nodesRegistryPath`, `nodes_registry_url`
   - `config["nodes"]["registry_path"|"registry"|"registry_url"|"registryPath"]`
4) Environment:
   - `THOMAS_NODES_REGISTRY_PATH`
   - `THOMAS_NODES_REGISTRY`
5) Inline JSON environment:
   - `THOMAS_NODES_REGISTRY_JSON`

Missing configuration raises a deterministic `nodes_registry_config_error`.

## Machine-readable output

The CLI module exports a Typer app with:

- `registry-model`
- `registry` (alias)

Example:

```bash
thomas nodes registry-model --source ./nodes.json --json
```

JSON output schema (success):

```json
{
  "ok": true,
  "schema_version": 1,
  "source": "file:/abs/path/nodes.json",
  "count": 2,
  "nodes": [
    { "id": "alpha", "endpoint": "http://alpha.local:8080", "labels": ["gpu"], "meta": {} }
  ]
}
```

Failures in `--json` mode return:

```json
{
  "ok": false,
  "schema_version": 1,
  "error": {
    "code": "nodes_registry_config_error",
    "message": "...",
    "details": { "...": "..." }
  }
}
```

## Error taxonomy

- `nodes_registry_config_error` — missing or invalid configuration (no source to load)
- `nodes_registry_input_error` — schema is wrong (missing id/endpoint, wrong types, duplicates, etc.)
- `nodes_registry_external_error` — I/O, network, UTF-8 decode, or JSON/YAML parse failures

## Request/response facade

For automation and HTTP routes, `run_nodes_registry_model()` (alias: `nodes_registry_model`) provides a **non-throwing** wrapper that always returns a machine-friendly union:

- success: `{ "ok": true, ... }`
- failure: `{ "ok": false, "schema_version": 1, "error": { ... } }`

Supported request keys: `source`, `label`, `id`, `timeout_s`, `config`, `env`.

This keeps failures deterministic even when a caller provides invalid request types.
