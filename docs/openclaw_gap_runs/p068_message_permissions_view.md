# P068 - Message permissions view

Thomas implements **message permissions view** as a lightweight capability that can be used from the CLI and embedded into server routes.

## What it does

Given a message identifier (and optionally a user identifier), it returns a mapping of permission names to booleans.

Backends supported:

1. **Static permissions** (offline runs / tests)
   - Configure via `THOMAS_MESSAGE_PERMISSIONS_VIEW_STATIC` (JSON object).
2. **Remote permissions backend** (real integrations)
   - Configure via `THOMAS_MESSAGE_PERMISSIONS_VIEW_ENDPOINT` (URL) and optionally `THOMAS_MESSAGE_PERMISSIONS_VIEW_TOKEN`.

Optional:
- `THOMAS_MESSAGE_PERMISSIONS_VIEW_TIMEOUT_S` (float seconds, default `10.0`).

## CLI

Command shape (nested under `messages permissions`):

```bash
thomas messages permissions view --message-id msg_123 --user-id user_1
```

Machine-readable output:

```bash
thomas messages permissions view --message-id msg_123 --user-id user_1 --json
```

Override config from CLI (useful in automation):

```bash
thomas messages permissions view --message-id msg_123 --json --static-permissions '{"view": true, "delete": false}'
```

## Remote backend response shape

Either of these is accepted:

```json
{"view": true, "delete": false}
```

or:

```json
{"permissions": {"view": true, "delete": false}}
```

## JSON schema

Success:

```json
{
  "ok": true,
  "result": {
    "message_id": "msg_123",
    "user_id": "user_1",
    "permissions": {"view": true, "delete": false},
    "source": "static"
  }
}
```

Failure:

```json
{
  "ok": false,
  "error": {
    "code": "missing_config",
    "message": "...",
    "details": {"required": ["THOMAS_MESSAGE_PERMISSIONS_VIEW_STATIC", "THOMAS_MESSAGE_PERMISSIONS_VIEW_ENDPOINT"]}
  }
}
```

## Deterministic error codes

- `invalid_input`
- `missing_config`
- `external_failure`
