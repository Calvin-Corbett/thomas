# P078 — Channel add command

## What this adds

A `channels add` operation for Thomas that:

- validates input deterministically (stable error codes)
- updates the config shape under `channels.<channel>.accounts.<account>`
- writes config atomically (temp file + replace)
- supports automation-friendly output (`--json`)

## CLI usage

Human output:

```bash
thomas channels add --channel telegram --token 123:abc
```

JSON output:

```bash
thomas channels add --channel telegram --token 123:abc --json
```

Optional:

- `--account <id>` (defaults to `default`)
- `--name <display name>`
- `--overwrite` (replace an existing entry)
- `--verify` (best-effort external validation; deterministic error if it fails)
- `--config <path>` (override config path resolution)

## Config shape written

The command ensures these keys exist:

- `channels.<channel>.enabled = true`
- `channels.<channel>.accounts.<account>.enabled = true`

Token storage:

- For `telegram`, it writes `bot_token` at the account level and also at
  `channels.telegram.bot_token` for the `default` account (back-compat).
- For other channels, it writes `token` at the account level only.

## Deterministic error codes

- `invalid_input`
- `config_path_missing`
- `config_missing`
- `config_unreadable`
- `config_invalid`
- `account_exists`
- `config_write_failed`
- `telegram_verify_unavailable`
- `telegram_unreachable`
- `telegram_token_invalid`
