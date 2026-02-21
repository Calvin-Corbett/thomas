# P042 — Nodes camera action

This gap run adds a **Nodes camera action** primitive to Thomas. It’s intentionally small and boring (in the good way): validate input, call a configured Nodes service endpoint, return a typed result, and provide deterministic errors for automation.

## What it does

`nodes camera action` performs one of a small set of camera operations against a target node:

- `capture` — capture a still image
- `start_recording` / `stop_recording` — video recording control
- `start_stream` / `stop_stream` — stream control

The implementation is generic and assumes a Nodes service exists that can accept the request and perform the real work.

## Configuration

A Nodes base URL is required. Resolution order:

1. `--nodes-url` CLI option (highest priority)
2. Environment variables:
   - `THOMAS_NODES_URL`
   - `THOMAS_NODES_BASE_URL`
   - `THOMAS_NODE_SERVICE_URL`
   - `NODES_URL`
   - `NODES_BASE_URL`
3. Best-effort lookup from `thomas.config` (if present)

Optional bearer auth token:

- `--token` CLI option
- or `THOMAS_NODES_TOKEN` / `THOMAS_NODE_SERVICE_TOKEN` / `NODES_TOKEN`

Optional endpoint template override:

- `THOMAS_NODES_CAMERA_ACTION_TEMPLATE` (default: `/nodes/{node_id}/camera/action`)

## CLI usage

Two equivalent command shapes are supported (depends on how your CLI is wired):

### Flat form

```bash
thomas nodes camera-action NODE_ID capture --camera 0 --param format=jpeg
```

### Nested form

```bash
thomas nodes camera action NODE_ID capture --camera 0 --param format=jpeg
```

## Machine-readable output

Add `--json`:

```bash
thomas nodes camera-action node-1 capture --json
```

Example output:

```json
{
  "ok": true,
  "data": {
    "ok": true,
    "node_id": "node-1",
    "action": "capture",
    "camera": 0,
    "artifact": "http://cdn.local/photo.jpg",
    "payload": { "...": "..." }
  }
}
```

On failure (including config errors, HTTP errors, or a 200 response with `{"ok": false, ...}` from the Nodes service):

```json
{
  "ok": false,
  "error": {
    "code": "MISSING_CONFIG",
    "message": "Nodes service base URL is not configured.",
    "details": {
      "expected": ["THOMAS_NODES_URL", "THOMAS_NODES_BASE_URL", "THOMAS_NODE_SERVICE_URL"]
    }
  }
}
```
