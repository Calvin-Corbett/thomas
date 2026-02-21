# P045 — Nodes canvas action

This run adds a **nodes canvas action** capability to Thomas.

## Behavior

A “canvas” is treated as a small persisted state object:

- `viewport`: `x`, `y`, `zoom`
- `selection`: `selected_node_ids`

An action applies an operation to a canvas and returns the updated state.

## Supported operations

- `pan` with payload `{ "dx": number, "dy": number }`
- `zoom` with payload `{ "factor": number (> 0) }`
- `select` with payload `{ "node_ids": [string, ...] }`
- `focus` with payload `{ "node_id": string }`
- `clear-selection` with payload `{}`

Notes:

- `select` de-duplicates node IDs while preserving order.
- Missing state store on disk is treated as an empty store (defaults are used until first write).

## Persistence

By default the state store is written to:

- `$THOMAS_STATE_DIR/nodes_canvas_state.json`, if `THOMAS_STATE_DIR` is set
- otherwise `~/.thomas/state/nodes_canvas_state.json`

The file is created on first write and updated atomically.

## CLI

The command supports machine-readable output:

```bash
thomas nodes canvas action pan \
  --canvas-id default \
  --payload '{"dx": 5, "dy": -2}' \
  --json
```

### JSON output

Success:

```json
{
  "ok": true,
  "canvas_id": "default",
  "operation": "pan",
  "applied": true,
  "state": {
    "viewport": {"x": 5.0, "y": -2.0, "zoom": 1.0},
    "selected_node_ids": []
  }
}
```

Failure:

```json
{
  "ok": false,
  "error": {"code": "...", "message": "..."}
}
```
