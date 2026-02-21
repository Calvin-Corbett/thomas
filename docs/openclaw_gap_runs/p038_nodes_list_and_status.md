# P038 - Nodes list and status

## What this adds

Thomas gains a **node inventory + reachability probe**:

- **List nodes** from Thomas configuration
- **Probe status** by attempting a TCP connection to each node’s host/port
- Support **human output** and **machine-readable JSON** (`--json`)

This is *Thomas-native* behavior: no OpenClaw naming is reused.

## CLI

The command is registered under the `nodes` group:

```bash
thomas nodes list
thomas nodes status      # alias
thomas nodes list --json
thomas nodes list --strict
```

### JSON schema (automation)

Success:

```json
{
  "ok": true,
  "result": {
    "nodes": [
      {
        "id": "node-a",
        "label": null,
        "address": "http://127.0.0.1:8080",
        "status": "online",
        "online": true,
        "latency_ms": 3,
        "error": null
      }
    ],
    "summary": { "online": 1, "offline": 0, "total": 1 }
  }
}
```

Failure:

```json
{
  "ok": false,
  "error": { "code": "missing_config", "message": "...", "details": { "...": "..." } }
}
```

## Configuration contract

Nodes are resolved from a provided config mapping (preferred), or from a config file path
provided via one of:

- `THOMAS_CONFIG`
- `THOMAS_CONFIG_PATH`
- `THOMAS_SETTINGS`

The loader looks for nodes at (first match wins):

- `nodes`
- `cluster.nodes`
- `thomas.nodes`
- `browser.nodes`

A node entry may be:

- Mapping form:

  ```json
  { "id": "node-a", "url": "http://127.0.0.1:8080" }
  ```

- Dict form (node_id -> url):

  ```json
  { "node-a": "http://127.0.0.1:8080" }
  ```

## Error contract

Errors are deterministic and carry a stable `code`:

- `invalid_input`
- `missing_config`
- `external_failure` (only emitted when `--strict` is used and one or more nodes are unreachable)
