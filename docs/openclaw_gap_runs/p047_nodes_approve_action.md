# P047 — Nodes approve action

## Summary

Thomas needs a **native** way to record that an *action* has been approved for one or more **nodes**.

This prompt adds a small, deterministic approval recorder:

- Validates input (`action_id`, optional `node_ids`, metadata).
- Resolves an approvals ledger location from either:
  - an explicit `--state-path`, or
  - `THOMAS_NODES_APPROVALS_PATH`, or
  - a best-effort fallback to `THOMAS_STATE_DIR` / `THOMAS_STATE_PATH` / `THOMAS_HOME`.
- Appends a single JSON line (JSONL) record per approval.

This design keeps the feature usable in automation and server contexts without requiring a database.

## CLI

A new CLI subcommand is added under the `nodes` command group:

```bash
thomas nodes approve-action ACTION_ID \
  --node NODE_ID --node NODE_ID \
  --approver "NAME" \
  --comment "TEXT" \
  --state-path /path/to/approvals.jsonl \
  --json
```

### Machine-readable output

When `--json` is set:

- Success:

```json
{"ok": true, "result": {"action_id": "...", "approved_nodes": ["..."], "ledger_path": "..."}}
```

- Failure:

```json
{"ok": false, "error": {"code": "missing_config", "message": "...", "details": {...}}}
```

## Core API

`thomas.nodes.p047_nodes_approve_action` defines clear contracts:

- `NodesApproveActionRequest` (dataclass)
- `NodesApproveActionResult` (dataclass)

And deterministic error types:

- `NodesApproveActionInputError` (`code=invalid_input`)
- `NodesApproveActionConfigError` (`code=missing_config`)
- `NodesApproveActionExternalError` (`code=external_failure`)

## Storage format

Approvals are appended to a **JSONL** file. Each line is a record like:

```json
{
  "schema_version": 1,
  "action_id": "act-123",
  "approved": true,
  "approved_nodes": ["node-a", "node-b"],
  "scope": "nodes",
  "approver": "calvin",
  "comment": "ship it",
  "approved_at": "2025-01-02T03:04:05Z"
}
```

Notes:

- If `approved_nodes` is empty, the intent is "approve for all nodes" and `scope` will be `all`.

## Tests

`tests/prompt_pack/test_p047_nodes_approve_action.py` covers:

- Success path (writes one JSONL record).
- Invalid input.
- Missing config.
- Fallback config via `THOMAS_STATE_DIR`.
- External write failure.
- CLI `--json` success + failure behavior.
