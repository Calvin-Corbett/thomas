# P049 — Nodes pairing handshake

## What this adds

A **Thomas-native node pairing handshake** primitive that creates (or reuses) a
short‑lived *pending pairing request* in the Thomas state directory. This gives
operators and automation a clean, deterministic way to start node onboarding.

This implementation intentionally does **not** reuse OpenClaw naming.

## Contracts

### Input (machine / API)

```json
{
  "node_id": "node-123",
  "display_name": "Kitchen iPad",
  "silent": false
}
```

- `node_id` is required and must match: `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`
- `display_name` is optional (max 120 chars)
- `silent` is an optional hint; it does not change security behavior

### Output (machine / API)

Success:

```json
{
  "ok": true,
  "payload": {
    "request_id": "…",
    "node_id": "node-123",
    "display_name": "Kitchen iPad",
    "expires_at_ms": 1700000000000,
    "created": true
  }
}
```

Failure:

```json
{
  "ok": false,
  "error": {
    "code": "invalid_input",
    "message": "node_id is required"
  }
}
```

Stable error codes:

- `invalid_input`
- `missing_config`
- `storage_error`
- `external_failure`

## Storage

State directory (resolved via `--state-dir`, `THOMAS_STATE_DIR`, or default):

- `nodes/pending.json` — dict keyed by `request_id`
- `nodes/pending.lock` — best-effort cross-platform lock file (atomic create)

Pending requests are pruned on read (expired entries removed).

## CLI

Command:

- `thomas nodes pairing-handshake --node-id NODE [--display-name NAME] [--silent] [--json]`

Machine output uses `--json`.

## Notes

This prompt only implements the handshake (creating/reusing a pending request).
Approval and issuance of long-lived credentials are intentionally out of scope.
