# P039 - Nodes invoke action

## What this adds

Thomas now supports invoking a **named action** on a configured **node**.

The feature is exposed as a Thomas-native CLI command under the `nodes` command group.
It takes:

- a node identifier (or direct node URL)
- an action name
- an optional JSON payload

and returns either...

- a human-readable summary (default)
- or machine-readable JSON (`--json`)

## CLI usage

```bash
# Invoke "ping" on node "n1" with an empty payload
thomas nodes invoke-action --node n1 --action ping

# Invoke with a payload
thomas nodes invoke-action --node n1 --action run_job --payload '{"job_id": "42"}'

# Automation-friendly output
thomas nodes invoke-action --node n1 --action ping --json
```

### Node registry configuration

Node identifiers are resolved via a simple registry mapping.

One supported approach is setting `THOMAS_NODE_REGISTRY` to a JSON object:

```bash
export THOMAS_NODE_REGISTRY='{"n1": "http://127.0.0.1:8081"}'
```

Alternatively, set `THOMAS_NODE_REGISTRY_FILE` to point at a JSON file with the same mapping.

### Invocation endpoint

By default, Thomas will POST to:

- `<node_base_url>/actions/invoke`

You can override the path with:

- `THOMAS_NODE_INVOKE_PATH=/some/other/path`

## Error contract

Failures return deterministic error payloads in JSON mode:

```json
{
  "ok": false,
  "node": "n1",
  "action": "ping",
  "status_code": 503,
  "error": {
    "code": "transport_failure",
    "message": "Failed to reach node endpoint",
    "details": {"endpoint": "http://..."}
  }
}
```

## Notes

- This implementation is Thomas-native and does not reuse external naming.
- The core logic lives in `thomas.nodes.p039_nodes_invoke_action` and is reusable from both CLI and server contexts.
