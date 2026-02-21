# P062 - Message reactions add/remove/list

## What shipped

Thomas-native support for managing **reactions on a message**:

- Add a reaction
- Remove a reaction
- List reactions

Implemented in:

- `thomas/messages/p062_message_reactions_add_remove_list.py` (core logic + backend interface)
- `thomas/cli/commands/messages/p062_message_reactions_add_remove_list.py` (CLI surface)
- `tests/prompt_pack/test_p062_message_reactions_add_remove_list.py` (success + failure tests)

## CLI usage

These commands are designed to be mounted under your existing `messages` group:

```bash
thomas messages reactions add --message-id <id> --emoji ":rocket:"
thomas messages reactions remove --message-id <id> --emoji ":rocket:"
thomas messages reactions list --message-id <id>
```

### Automation mode (machine-readable)

All subcommands support `--json`:

```bash
thomas messages reactions add --message-id m1 --emoji ":rocket:" --json
```

Example JSON:

```json
{"ok":true,"action":"add","message_id":"m1","channel_id":null,"emoji":":rocket:","applied":true}
```

## Backends

### In-memory (tests + local)

Use `--backend memory` or set:

- `THOMAS_MESSAGE_REACTIONS_BACKEND=memory`

### HTTP (delegation)

Use `--backend http` plus either CLI flags or env vars:

- CLI: `--api-base-url http://127.0.0.1:8080`
- Env: `THOMAS_API_BASE_URL=http://127.0.0.1:8080`
- Optional: `THOMAS_API_TOKEN=...`
- Optional: `THOMAS_API_TIMEOUT_SECONDS=10`

The HTTP backend expects placeholder endpoints (adjust once server routes exist):

- `POST /messages/reactions/add`
- `POST /messages/reactions/remove`
- `GET  /messages/reactions/list?message_id=...&channel_id=...`

## Error behavior

Errors are deterministic and machine-readable:

```json
{
  "ok": false,
  "error": {
    "code": "missing_config",
    "message": "Message reactions backend is not configured",
    "details": {
      "expected_env": ["THOMAS_MESSAGE_REACTIONS_BACKEND"]
    }
  }
}
```
