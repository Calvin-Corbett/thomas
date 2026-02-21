# P085 — Channel list enriched output

This adds a **Thomas-native** way to list messaging channels with richer, automation-friendly metadata.

## What it does

- Lists available channels from the configured messaging integration (default: `telegram`).
- Produces an **enriched** representation for each channel (id, name, kind/type, username, member count when available, privacy when available).
- Supports `--json` output for scripting/automation.

## CLI usage

```bash
thomas channels list --limit 100 --offset 0
thomas channels list --json
thomas channels list --integration telegram --json
```

## JSON contract

Success:

```json
{
  "count": 1,
  "channels": [
    {
      "id": "123",
      "name": "My Group",
      "platform": "telegram",
      "kind": "group",
      "username": "mygroup",
      "member_count": 42,
      "is_private": false,
      "meta": {}
    }
  ]
}
```

Failure:

```json
{
  "error": {
    "code": "missing_config",
    "message": "No integration client available for 'telegram'."
  }
}
```

## Error codes

- `invalid_input` — Bad CLI arguments (e.g., negative `--limit` / `--offset`).
- `missing_config` — No configured integration client could be found in the CLI context.
- `missing_capability` — The integration client does not support listing channels.
- `external_failure` — The integration raised an exception; wrapped deterministically.

## Notes

The core logic uses runtime introspection when interacting with integration clients so it can adapt across integrations and evolving interfaces without leaking third-party object shapes into CLI output.

Async-first integrations are supported when the integration returns an awaitable and no event loop is already running (typical CLI usage). If a loop is already running, the error is returned deterministically.
