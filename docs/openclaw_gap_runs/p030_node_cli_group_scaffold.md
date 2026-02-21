# P030 - Node CLI group scaffold

This gap run adds a **Thomas-native** `nodes` CLI group to cover the "node(s)" command surface area expected by CLI parity tests.

## What shipped

- `thomas nodes list` — list known nodes from either:
  - a config file (`--config`), or
  - a server URL (`--server`)
- `thomas nodes show <node_id>` — display a single node record
- Machine-readable output mode via `--json` on each subcommand.
- Deterministic error kinds/codes and deterministic exit codes for automation.

Aliases are also exposed for parity coverage:

- `thomas node ...`
- `thomas devices ...`
- `thomas device ...`

## Config format (minimal)

The scaffold accepts JSON/TOML config files, plus a small YAML subset (no external YAML dependency).

A config file contains a `nodes` list.

Example (YAML):

```yaml
nodes:
  - id: alpha
    label: Alpha
    address: http://alpha.local
  - id: beta
    label: Beta
```

Example (TOML):

```toml
nodes = [
  { id = "alpha", label = "Alpha", address = "http://alpha.local" },
  { id = "beta", label = "Beta" },
]
```

## Automation output

Success (`nodes list --json`):

```json
{"ok": true, "result": {"source": "config", "endpoint": null, "nodes": [{"id": "alpha", "label": "Alpha", "address": "http://alpha.local"}]}}
```

Success (`nodes show --json`):

```json
{"ok": true, "result": {"source": "config", "endpoint": null, "node": {"id": "alpha", "label": "Alpha", "address": "http://alpha.local"}}}
```

Failure:

```json
{"ok": false, "error": {"kind": "config", "code": "missing_node_source", "message": "No node source configured. Provide --server, --config, or set THOMAS_SERVER_URL / THOMAS_NODES_CONFIG."}}
```

Exit codes:

- `2` → input error
- `3` → config error
- `4` → external dependency error (network/server)
- `1` → internal/unexpected error

## Notes

This is intentionally a *scaffold*: it provides the CLI group and the core contracts needed for downstream node functionality without baking in OpenClaw naming or assumptions.
