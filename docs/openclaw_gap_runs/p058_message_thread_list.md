# P058 — Message thread list

## Summary
Thomas can list message threads (conversation roots) from the configured
messaging backend.

This implementation is Thomas-native (no OpenClaw naming reuse) while still
supporting automation via `--json`.

## CLI

### Human-readable

```bash
thomas message-thread-list --limit 20
```

### Machine-readable JSON

```bash
thomas message-thread-list --json --limit 50
```

The JSON envelope includes a stable boolean `ok`:

- Success: `{ "ok": true, "threads": [...], "next_cursor": ... }`
- Failure: `{ "ok": false, "error": {"code": ..., "message": ..., "details": ... } }`

### Local JSONL store (fallback backend)

If you don't have a messaging backend configured, you can point the command at
an on-disk JSONL message store:

```bash
thomas message-thread-list --store /path/to/messages.jsonl --json
```

Environment variables are also supported:

- `THOMAS_MESSAGE_STORE_PATH`
- `THOMAS_MESSAGES_STORE_PATH`
- `THOMAS_MESSAGE_THREAD_STORE_PATH`

## Input contract

The Python entrypoint uses `MessageThreadListRequest`:

- `channel_id: str | None` — optional filter
- `limit: int` — 1..200
- `cursor: str | None` — pagination cursor (integer offset for the JSONL backend)
- `include_archived: bool`

## Output contract

A `MessageThreadListResponse` with:

- `threads: list[MessageThreadSummary]`
- `next_cursor: str | None`

Each `MessageThreadSummary` contains:

- `thread_id: str`
- `channel_id: str | None`
- `title: str | None`
- `last_message_at: ISO-8601 str | None`
- `message_count: int`
- `participants: list[str]`

## Errors

Errors are deterministic and machine-readable.

```json
{
  "ok": false,
  "error": {
    "code": "invalid_input | missing_config | external_failure",
    "message": "...",
    "details": {"field": "..."}
  }
}
```
