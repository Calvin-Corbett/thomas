# P040 - Nodes notify action

## Summary

This prompt adds a **Thomas-native** `nodes notify-action` capability.

It is implemented as:

- **Core**: `thomas.nodes.p040_nodes_notify_action`
- **CLI**: `thomas nodes notify-action` (argparse entry point)

The core logic is transport-agnostic. Callers may inject a `NodesActionNotifier`
implementation. A default HTTP notifier is provided for real usage, while tests
and automation can inject a fake notifier.

## CLI usage

Human output:

```bash
thomas nodes notify-action --node n-1 --node n-2 --action ping
```

Machine-readable output:

```bash
thomas nodes notify-action --node n-1 --action ping --json
```

### JSON output (success)

```json
{
  "ok": true,
  "action": "ping",
  "results": [
    {"node_id": "n-1", "ok": true, "status": 200}
  ]
}
```

### JSON output (failure)

```json
{
  "ok": false,
  "error": {
    "code": "missing_config",
    "message": "Nodes base URL is not configured",
    "details": {"env": "THOMAS_NODES_BASE_URL"}
  }
}
```

## Input / output contracts

The core contracts are defined as dataclasses:

- `NodesNotifyActionInput`
- `NodeNotifyResult`
- `NodesNotifyActionOutput`

JSON Schemas are exported as:

- `INPUT_JSON_SCHEMA`
- `OUTPUT_JSON_SCHEMA`

These can be used by an HTTP route implementation to validate request/response
payloads.

## Configuration

The default HTTP notifier can be configured via environment variables:

- `THOMAS_NODES_BASE_URL` (**required**) – base URL for the node manager
- `THOMAS_NODES_NOTIFY_PATH` (optional) – defaults to `/nodes/notify-action`
- `THOMAS_NODES_API_TOKEN` (optional) – bearer token
- `THOMAS_NODES_VERIFY_TLS` (optional) – set to `0`/`false` to disable TLS
  verification

## Deterministic errors

Errors raised by the core module are stable and machine-readable:

- `invalid_input`
- `missing_config`
- `external_failure`

Per-node transport errors are represented inside `results`:

- `remote_error` (non-2xx)
- `timeout`
- `network_error`
- `notifier_exception` (injected notifier raised unexpectedly)
