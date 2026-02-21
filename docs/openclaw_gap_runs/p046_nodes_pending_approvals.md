# P046 - Nodes pending approvals

## Summary

Thomas now supports listing **node approval requests that are still pending**.

This feature is implemented as Thomas-native behavior and exposes:

- A CLI command (human output + `--json` machine output)
- An optional aiohttp route returning JSON

## CLI

Command:

```bash
thomas nodes pending-approvals
```

Machine-readable output:

```bash
thomas nodes pending-approvals --json
```

Advanced override (useful for tests/automation):

```bash
thomas nodes pending-approvals --state-dir /path/to/state --json
```

## Output contract

Successful JSON shape:

```json
{
  "ok": true,
  "count": 2,
  "approvals": [
    {
      "node_id": "node-123",
      "requested_at": "2026-02-20T00:00:00Z",
      "requested_by": "alice",
      "reason": "new node enrollment",
      "metadata": {"ip": "10.0.0.5"}
    }
  ]
}
```

On error, the CLI emits deterministic errors in JSON mode:

```json
{
  "ok": false,
  "error": {
    "code": "NODES_PENDING_APPROVALS_CONFIG_MISSING",
    "message": "...",
    "details": {}
  }
}
```

## HTTP route

If aiohttp routes are registered, the endpoint is:

- `GET /nodes/pending-approvals`

It returns the same JSON schema as the CLI (`ok`, `count`, `approvals`), and returns
a structured error payload on failure.

## Storage model

Pending approvals are stored as a JSON list at:

```
<state_dir>/nodes/pending_approvals.json
```

The state directory is resolved in this order:

1. `--state-dir` CLI argument (or `NodesPendingApprovalsInput.state_dir`)
2. `THOMAS_STATE_DIR` environment variable
3. Thomas config discovery (best-effort, prefers `thomas.cli.parity_compat`)

If no state directory can be resolved, the operation fails with a deterministic
`NODES_PENDING_APPROVALS_CONFIG_MISSING` error.
