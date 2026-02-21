# P060 - Message pin command

This gap run adds a **Thomas-native** command for pinning a message in a channel.

## CLI

Command:

```bash
thomas messages pin --channel-id <channel> --message-id <message> \
  [--reason <text>] [--requested-by <who>] \
  [--backend memory|http] [--api-url <url>] [--api-token <token>] \
  [--timeout-seconds <n>] \
  [--json]
```

Behavior:

- **Idempotent**: pinning a message that is already pinned returns success with `already_pinned=true`.
- **Automation-friendly**: `--json` prints one JSON object to stdout (no log spew).

## Machine-readable output

Success (`--json`):

```json
{
  "ok": true,
  "result": {
    "pinned": true,
    "already_pinned": false,
    "channel_id": "C-123",
    "message_id": "M-456",
    "pin_id": "mempin_abcdef012345",
    "backend": "memory"
  }
}
```

Failure (`--json`):

```json
{
  "ok": false,
  "error": {
    "type": "config_error",
    "code": "missing_config",
    "message": "Missing API base URL for http backend.",
    "details": {
      "missing": ["THOMAS_MESSAGES_API_URL"],
      "backend": "http"
    }
  }
}
```

## Configuration

Environment variables:

- `THOMAS_MESSAGES_BACKEND` = `memory` | `http` (default: `http`)
- `THOMAS_MESSAGES_API_URL` = base URL for the http backend (**required** if backend=`http`)
- `THOMAS_MESSAGES_API_TOKEN` = bearer token (optional)
- `THOMAS_MESSAGES_TIMEOUT_SECONDS` = request timeout in seconds (default: `10`)

The implementation also tolerates singular aliases (`THOMAS_MESSAGE_*`) to reduce integration friction.

## Core API

The core function is:

- `thomas.messages.p060_message_pin_command.pin_message(MessagePinInput, config=..., http_post=...)`

There is also a convenience wrapper that returns a JSON-serializable dict without raising:

- `pin_message_json(payload_dict, config=..., http_post=...)`

## Notes

- This implementation is intentionally **Thomas-native** (no OpenClaw naming reuse).
- The http backend posts to: `{api_base_url.rstrip('/')}/messages/pin`.

---

Prompt: P060 | Batch: B08 | Lane: Messaging and Channels | Domain: messages
