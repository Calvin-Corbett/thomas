# P057 — Message search command

## What shipped

Thomas now supports a **message search** command with:

- A **core implementation**: `thomas/messages/p057_message_search_command.py`
- A **CLI wiring** module: `thomas/cli/commands/messages/p057_message_search_command.py`
- Deterministic error codes + `--json` output for automation
- Unit tests covering success + failure paths

## Behavior

The command supports two backends:

1) **Local message store (JSONL)**
- Preferred when configured (`--backend auto`)
- Searches a JSON Lines file for substring matches on the message content

2) **Discord guild message search**
- Used when no local store is configured, or when forcing `--backend discord`
- Calls the Discord guild message search endpoint

## CLI

Example:

```bash
thomas message search \
  --query "needle" \
  --limit 25
```

Force local backend:

```bash
thomas message search --query "needle" --backend local
```

Force Discord backend:

```bash
thomas message search \
  --query "needle" \
  --guild-id 1234567890 \
  --backend discord
```

### JSON mode

```bash
thomas message search --query "needle" --json
```

Success shape:

```json
{
  "ok": true,
  "total_results": 1,
  "hits": [
    {
      "message_id": "111",
      "channel_id": "222",
      "author_id": "333",
      "content": "…",
      "timestamp": "…",
      "url": "…"
    }
  ]
}
```

Failure shape:

```json
{
  "ok": false,
  "error": {
    "code": "missing_config|invalid_input|external_failure",
    "message": "…",
    "details": {"…": "…"}
  }
}
```

## Error codes

- `invalid_input`
  - Empty query, invalid backend value, invalid ids for Discord backend, limit out of range
- `missing_config`
  - No usable backend configured (no local store path and/or missing Discord credentials)
- `external_failure`
  - Local store unreadable, network failures, non-2xx responses, invalid JSON response

## Config expectations

### Local store

Supported config keys:

```json
{ "messages": { "store_path": "/path/to/messages.jsonl" } }
```

Or environment variable:

- `THOMAS_MESSAGE_STORE_PATH=/path/to/messages.jsonl`

### Discord

Supported config keys:

```json
{
  "channels": {
    "discord": {
      "token": "Bearer <token-or-auth-header>",
      "api_base": "https://discord.com/api/v9"
    }
  }
}
```

Or environment variable:

- `THOMAS_DISCORD_TOKEN="Bearer …"`
