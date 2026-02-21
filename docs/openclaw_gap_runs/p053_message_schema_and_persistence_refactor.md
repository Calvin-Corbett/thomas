# P053 - Message schema and persistence refactor

This implementation adds a Thomas-native, versioned **message schema (v1)** plus a **SQLite persistence layer**.

## What’s included

- `MessageRecord` (schema version `1`) — the canonical message shape
- `normalize_message(...)` — converts common inbound payload shapes into the canonical record
- `MessageStore` — SQLite-backed persistence with idempotent inserts (same `message_id` is ignored)
- `ingest_and_persist(...)` — normalize + persist helper
- `ingest_and_persist_safe(...)` — structured result payloads (no exceptions)
- Machine-readable JSON Schema dicts:
  - `MESSAGE_INGEST_JSON_SCHEMA`
  - `MESSAGE_INGEST_RESPONSE_JSON_SCHEMA`

## Store path resolution

Persistence location is resolved in this order:

1. Explicit store path (`--store` / `store_path=...`)
2. `THOMAS_MESSAGE_STORE` (or `THOMAS_MESSAGES_DB`, `THOMAS_MESSAGE_DB`)
3. `THOMAS_DATA_DIR` or `THOMAS_HOME` + `messages.sqlite3`

If no configuration is found, the API raises `MessageConfigError(code="missing_config")`.

## Deterministic errors

Errors are raised as subclasses of `ThomasMessageError` and can be serialized via `.to_dict()`:

- `invalid_input`
- `missing_config`
- `invalid_store_path`
- `unsupported_schema_version`
- `persistence_failure`
- `internal_error` (catch-all for unexpected failures in *_safe helpers)

## Examples

### Python

```python
from thomas.messages.p053_message_schema_and_persistence_refactor import ingest_and_persist

result = ingest_and_persist({"text": "hello", "channel": "ops", "sender": "calvin"})
print(result.to_dict())
```

### CLI JSON mode

```bash
thomas messages p053-message-schema-and-persistence-refactor --json --store ./messages.sqlite3 "hello"
```

### CLI payload from stdin

```bash
echo '{"text":"hello","channel":"ops"}' | thomas messages p053-message-schema-and-persistence-refactor --json --store ./messages.sqlite3 --payload -
```

### CLI list mode

```bash
thomas messages p053-message-schema-and-persistence-refactor --json --store ./messages.sqlite3 --list 20
```
