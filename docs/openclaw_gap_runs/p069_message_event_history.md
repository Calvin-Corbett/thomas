# P069 - Message event history (Thomas)

This gap run adds **message event history** support to Thomas.

## What it does

Thomas can receive message-related webhooks (delivery receipts, status changes, edits/deletes, reactions, etc.).  
This feature provides:

- **Append-only persistence** of inbound message events (JSON Lines storage).
- **Query**: retrieve the event timeline for a specific `message_id`.
- **Automation-friendly output** via CLI `--json`.

## Storage model

Events are stored as JSONL (one JSON object per line). A normalized record looks like:

```json
{
  "schema": "thomas.messages.event.v1",
  "message_id": "abc123",
  "event_type": "delivered",
  "occurred_at": "2025-01-02T03:04:05Z",
  "raw": { "...": "original webhook payload" }
}
```

Notes:

- `raw` preserves the provider payload.
- `schema` is present for normalized records; the reader will also accept raw provider-shaped
  payload lines (best-effort extraction) for backward compatibility.

### Store discovery

Discovery order:

1. `--store <path>` CLI override
2. `THOMAS_MESSAGE_EVENTS_PATH`
3. Autodiscovery in the Thomas state dir (`THOMAS_STATE_DIR`, then `THOMAS_HOME`, then `~/.thomas`)

Primary default write location (when no overrides are set):

- `<state>/messages/events.jsonl`

## CLI usage

Human output:

```bash
thomas messages message-event-history <message_id>
```

Machine-readable output:

```bash
thomas messages message-event-history <message_id> --json
```

Example JSON:

```json
{
  "ok": true,
  "schema": "thomas.messages.event_history.v1",
  "message_id": "abc123",
  "events": [
    {
      "message_id": "abc123",
      "event_type": "sent",
      "occurred_at": "2025-01-01T00:00:00Z",
      "raw": {},
      "source_path": "/.../messages/events.jsonl"
    }
  ],
  "source_paths": ["/.../messages/events.jsonl"]
}
```

On failure:

```json
{
  "ok": false,
  "error": {
    "code": "messages.event_history.missing_config",
    "message": "Message event store not configured or no store file found.",
    "details": { "...": "..." }
  }
}
```
