# P067 - Message role assign and remove

This gap run covers **assigning** and **removing** a Discord role for a guild member.

## Thomas behavior

Thomas implements a small, deterministic role mutation wrapper:

- `thomas message role assign --guild-id <id> --user-id <id> --role-id <id>`
- `thomas message role remove --guild-id <id> --user-id <id> --role-id <id>`

### Machine-readable output

Both subcommands support `--json`.

Success example:

```json
{"ok": true, "provider": "discord", "action": "assign", "guild_id": "...", "user_id": "...", "role_id": "...", "status_code": 204}
```

Failure example:

```json
{"ok": false, "error": {"code": "missing_config", "message": "...", "details": {"expected_env": ["THOMAS_DISCORD_BOT_TOKEN", "..."]}}}
```

## Config / auth

Role mutations require a Discord **bot token** with sufficient permissions (typically **Manage Roles**).

Token resolution order:

1. `--token` (CLI override)
2. Environment: `THOMAS_DISCORD_BOT_TOKEN`, `THOMAS_DISCORD_TOKEN`, `DISCORD_BOT_TOKEN`, `DISCORD_TOKEN`
3. Best-effort Thomas config loader (if `thomas.config.load_config` is present)

## Notes

- Discord returns HTTP `204 No Content` on success for these endpoints.
- If Discord returns `429`, Thomas includes rate-limit hints (retry-after/bucket) in error details.
