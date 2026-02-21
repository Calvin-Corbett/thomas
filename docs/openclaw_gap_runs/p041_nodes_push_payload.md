# P041 — Nodes push payload

## Summary

Implements a Thomas-native **nodes push payload** operation.

Given one or more node identifiers (URLs or IDs), Thomas will `POST` a JSON
payload to each node and return a structured per-node result list.

This implementation avoids OpenClaw naming reuse; it is framed in terms of
**nodes**, **payloads**, and **push results**.

## CLI

Command module: `thomas/cli/commands/nodes/p041_nodes_push_payload.py`

Examples:

```bash
# Push inline JSON to two nodes
thomas nodes push-payload \
  --node http://10.0.0.12:8080 \
  --node http://10.0.0.13:8080 \
  --payload '{"job": "reconfigure", "dry_run": true}'

# Read payload from a file and emit machine-readable JSON
thomas nodes push-payload \
  --node http://10.0.0.12:8080 \
  --payload @payload.json \
  --json
```

### Node identifiers

* If `--node` is an **http(s) URL**:
  * If it already includes a non-root path (e.g. `/custom/endpoint`), it is
    treated as the full target URL.
  * Otherwise, `--endpoint-path` (default: `/payload`) is appended.
* If `--node` is **not** a URL, it is treated as a node ID and requires
  `--node-map` (JSON object mapping IDs to base URLs).

### Machine-readable output

* `--json` emits deterministic JSON to stdout (sorted keys, stable shape).
* Exit codes:
  * `0` — all nodes succeeded
  * `1` — at least one node failed
  * `2` — invalid input / missing config

## Programmatic API

Core implementation: `thomas/nodes/p041_nodes_push_payload.py`

Key contracts:

* `NodesPushPayloadRequest` (dataclass): inputs
* `NodesPushPayloadResponse` (dataclass): outputs
* `push_payload_to_nodes(req)` (async)
* `push_payload_to_nodes_sync(req)` (sync wrapper)

### Deterministic errors

Errors are surfaced via `NodesPushPayloadError(code=...)`:

* `invalid_input` — malformed arguments (e.g., empty nodes, non-serializable payload)
* `missing_config` — node ID given without an ID→URL mapping
* `invalid_config` — mapping exists but URL is not a valid absolute http(s) URL

External failures (timeouts, network errors, non-2xx responses) are captured per
node in `NodePushPayloadResult.error_code`.

### JSON schema

For route integrations that prefer schemas, this module also exposes:

* `REQUEST_JSON_SCHEMA`
* `RESPONSE_JSON_SCHEMA`

These are intended for validation and documentation in Thomas' HTTP layer.
