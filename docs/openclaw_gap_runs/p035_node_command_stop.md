# P035 – Node command stop

This change adds a **Thomas-native** node lifecycle operation: **stop**.

## What it does

- Stops a node identified by `node_id`.
- Uses explicit **input/output contracts** (dataclasses) and deterministic error codes.
- Emits **human-friendly** output by default.
- Emits **machine-readable JSON** with `--json`.

## CLI

```bash
thomas nodes stop <node_id>
thomas nodes stop <node_id> --force
thomas nodes stop <node_id> --timeout 10
thomas nodes stop <node_id> --config path/to/config.json
thomas nodes stop <node_id> --json
```

### JSON output shape

Success:

```json
{"ok": true, "node_id": "node-1", "stopped": true, "message": "Node 'node-1' stopped"}
```

Failure:

```json
{"ok": false, "error": {"code": "...", "message": "...", "details": {}}}
```

## Deterministic errors

- `THOMAS_NODE_STOP_INVALID_INPUT`
  - Invalid `node_id`, invalid types, or invalid flag values.
- `THOMAS_NODE_STOP_MISSING_CONFIG`
  - `--config` points to a missing/unreadable/unparseable file.
- `THOMAS_NODE_STOP_EXTERNAL_FAILURE`
  - Underlying backend could not be resolved or reported failure.

## Backend delegation

The stop implementation delegates to the existing Thomas node-control backend using:

1. Explicit override via `THOMAS_NODE_STOP_BACKEND="module:function"`, or
2. Discovery of common internal module targets, followed by
3. A limited scan of `thomas.nodes.*` modules for a callable `stop_node`/`node_stop`/`stop`.

This keeps the command Thomas-native while staying resilient to internal refactors.
