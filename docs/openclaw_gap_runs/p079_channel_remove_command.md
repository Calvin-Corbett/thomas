# P079 — Channel remove command

Implements the **Thomas** CLI/channel behavior for removing a configured messaging channel (or channel account) from the local Thomas configuration.

This is a *Thomas-native* implementation (no OpenClaw naming reuse), while still supporting the automation-friendly `--json` output mode.

## CLI behavior

### Disable a channel (default)

Disabling keeps the configuration but marks the target as inactive by setting:

```json
"enabled": false
```

Example:

```bash
thomas channels remove --channel telegram
```

### Delete a channel (destructive)

Deletion removes the channel entry from config.

Example:

```bash
thomas channels remove --channel telegram --delete
```

### JSON output

For scripting/automation:

```bash
thomas channels remove --channel telegram --delete --json
```

Success response shape:

```json
{
  "ok": true,
  "success": true,
  "result": {
    "channel": "telegram",
    "account": "default",
    "action": "deleted",
    "changed": true,
    "config_path": "/home/user/.thomas/config.json"
  },
  "error": null
}
```

Failure response shape:

```json
{
  "ok": false,
  "success": false,
  "result": null,
  "error": {
    "code": "CHANNEL_NOT_FOUND",
    "message": "Channel not configured: telegram",
    "details": { "channel": "telegram" }
  }
}
```

## Deterministic errors

The core implementation raises `ChannelRemoveError` with stable codes:

- `INVALID_INPUT`
- `CONFIG_NOT_FOUND`
- `CONFIG_INVALID`
- `CHANNEL_NOT_FOUND`
- `ACCOUNT_NOT_FOUND`
- `WRITE_FAILED`
- `EXTERNAL_FAILURE`

These map to stable exit codes for automation.

## Acceptance checks (run locally)

```bash
python -m pytest -q tests/prompt_pack/test_p079_channel_remove_command.py
python -m pytest -q tests/test_cli_parity_commands.py -k "channels"
```

## Notes / integration risk

The exact CLI registration surface inside `thomas/cli/commands/channels.py` can vary (argparse vs Typer vs custom registry).
This module provides multiple registration aliases (`register`, `register_command`, `build_parser`, etc.) to reduce friction, but if
your channels command loader expects a different hook shape, you may need a tiny adapter in `channels.py` to call `register(...)`.
