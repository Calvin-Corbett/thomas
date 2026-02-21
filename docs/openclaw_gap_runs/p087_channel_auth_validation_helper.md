# P087 - Channel auth validation helper (v2)

This adds a **Thomas-native** helper to validate that a messaging channel integration has usable authentication configured.

## What it does

- Validates auth for a given channel (currently **Telegram**)
- Produces deterministic error codes for automation
- CLI supports machine-readable JSON via `--json`
- Offline tests by monkeypatching the HTTP layer

## CLI usage

Validate Telegram auth (token override):

```bash
thomas channels validate-auth telegram --token "$TELEGRAM_BOT_TOKEN"
```

JSON output for automation:

```bash
thomas channels validate-auth telegram --token "$TELEGRAM_BOT_TOKEN" --json
```

## JSON schema (shape)

Success:

```json
{
  "ok": true,
  "channel": "telegram",
  "valid": true,
  "identity": { "id": "123", "username": "my_bot", "display_name": "My Bot" },
  "details": { "source": "override" }
}
```

Failure:

```json
{
  "ok": false,
  "error": {
    "code": "MISSING_CONFIG",
    "message": "missing authentication credentials for channel 'telegram'",
    "channel": "telegram",
    "details": { "expected_env_vars": ["THOMAS_TELEGRAM_TOKEN", "..."] }
  }
}
```

## Supported channels

- `telegram` (alias: `tg`)

## Deterministic error codes

- `INVALID_INPUT` — invalid channel name, invalid timeout, etc.
- `MISSING_CONFIG` — no token found in override/config/env
- `EXTERNAL_FAILURE` — network/API failure or upstream rejection

## Implementation notes

- Core logic: `thomas/channels/p087_channel_auth_validation_helper.py`
- CLI command: `thomas/cli/commands/channel_ops/p087_channel_auth_validation_helper.py`
- Telegram validation attempts `thomas.integrations.telegram` if present and compatible, then falls back to a minimal HTTPS `getMe` request using Python stdlib (no extra deps).
