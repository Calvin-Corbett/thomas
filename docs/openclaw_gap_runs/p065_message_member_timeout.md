# P065 - Message member timeout

## What this does

Implements a **member timeout** action as Thomas-native behavior.

Given:
- a guild/server ID
- a member/user ID
- a timeout duration (seconds)

Thomas calls the upstream provider API to temporarily disable the member's ability to
communicate. Primary target: Discord's `communication_disabled_until`.

## Contracts

### Input (payload)

Supported keys:

- `guild_id` (required, string) — numeric server ID
- `user_id` (required, string) — numeric member ID
- `duration_seconds` (required, integer) — timeout duration in seconds
  - numeric strings are also accepted for automation convenience
- `reason` (optional, string) — audit log reason (<= 512 chars)
- `message_id` (optional, string) — traceability only

Aliases:
- `server_id` → `guild_id`
- `member_id` → `user_id`
- `seconds` → `duration_seconds`

### Output

Success:

```json
{
  "ok": true,
  "result": {
    "guild_id": "123",
    "user_id": "456",
    "duration_seconds": 60,
    "timed_out_until": "2026-02-20T00:01:00.000Z"
  }
}
```

Failure:

```json
{
  "ok": false,
  "error": {
    "code": "MISSING_CONFIG",
    "message": "Missing required configuration: bot_token.",
    "details": {
      "missing": "bot_token"
    }
  }
}
```

## Error codes

- `INVALID_INPUT` — malformed IDs, invalid duration, invalid config values
- `MISSING_CONFIG` — missing required configuration (e.g. bot token)
- `EXTERNAL_FAILURE` — upstream API call failed or returned a non-2xx status

## CLI usage

Machine-readable mode for automation:

```bash
python -m thomas.cli parity messages p065-message-member-timeout \
  --guild-id 123 \
  --user-id 456 \
  --duration-seconds 60 \
  --reason "cool off" \
  --json
```

Token can be provided via `--token` or the `THOMAS_DISCORD_BOT_TOKEN` environment variable.
