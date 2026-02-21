# P081 - Channel logout command

Implements a **Thomas-native** channel logout operation that removes locally stored
authentication/session state for a given messaging channel (e.g. `telegram`).

This command is designed for automation as well as interactive use.

## CLI

Typical usage:

- Human-readable:

```bash
thomas channels logout telegram
```

- Machine-readable:

```bash
thomas channels logout telegram --json
```

Optional flags:

```bash
thomas channels logout telegram --dry-run
thomas channels logout telegram --config-root /path/to/config
thomas channels logout telegram --hooks
thomas channels logout telegram --no-integration-hints
```

## Input contract

`ChannelLogoutRequest` (dataclass):

- `channel` (str): channel identifier (e.g. `telegram`)
- `config_root` (Path | None): override the Thomas config directory
- `dry_run` (bool): report what would be removed without changing anything
- `call_integration_hooks` (bool): optional integration cleanup hooks (default: `False`)
- `include_integration_hints` (bool): use integration hints to locate state files (default: `True`)

## Output contract

`ChannelLogoutResult` (dataclass):

- `channel` (str): normalized channel identifier
- `removed` (tuple[str, ...]): paths that were removed or edited
- `dry_run` (bool): whether the run made changes

### JSON success payload (`--json`)

```json
{
  "ok": true,
  "channel": "telegram",
  "removed": [
    "/home/user/.thomas/channels/telegram.json"
  ],
  "dry_run": false
}
```

### JSON failure payload (`--json`)

```json
{
  "ok": false,
  "error": {
    "code": "not_logged_in",
    "message": "No saved auth state found for channel 'telegram'."
  }
}
```

## Deterministic error codes

- `invalid_input`: missing/blank channel name
- `missing_config`: Thomas config directory does not exist
- `unknown_channel`: channel is not recognized and no state was found
- `not_logged_in`: no saved state exists for that channel
- `external_failure`: filesystem or optional integration cleanup failure
