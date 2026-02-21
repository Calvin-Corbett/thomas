# P101 - Plugin enablement store

This adds **persistent** enable/disable state for Thomas plugins via a small JSON-backed store.

The goal is simple: if a plugin is disabled, that decision should remain true across process runs until re-enabled.

## What shipped

- Enablement store implementation:
  - `thomas/plugins/p101_plugin_enable_and_disable_state_store.py`
- CLI wrapper with automation-friendly output:
  - `thomas/cli/commands/plugins/p101_plugin_enable_and_disable_state_store.py`

## Storage format

Schema v1 JSON:

```json
{
  "schema_version": 1,
  "updated_at": 1700000000.0,
  "plugins": {
    "some-plugin": {"enabled": false, "updated_at": 1700000000.0}
  }
}
```

Default behavior:
- If a plugin has no entry in the store, it is treated as **enabled**.

## Default location resolution

If `--store-path` is not provided, the store path resolves in this order:

1. `THOMAS_PLUGIN_ENABLEMENT_STORE` (explicit file path)
2. `THOMAS_CONFIG_DIR` (directory; uses `plugin_enablement.json` inside it)
3. `XDG_CONFIG_HOME/thomas/plugin_enablement.json`
4. `~/.config/thomas/plugin_enablement.json`

## CLI usage

Disable a plugin:

```bash
thomas plugins disable some-plugin
```

Enable a plugin:

```bash
thomas plugins enable some-plugin
```

Query status for one plugin:

```bash
thomas plugins status some-plugin
```

List stored entries:

```bash
thomas plugins status
```

Remove a key (revert to default-enabled):

```bash
thomas plugins clear some-plugin
```

### JSON mode

All commands support `--json`:

Success:

```json
{"ok": true, "result": {"plugin": "some-plugin", "enabled": false, "...": "..."}}
```

Failure:

```json
{"ok": false, "error": {"code": "INVALID_PLUGIN_KEY", "message": "...", "details": {...}}}
```

## Deterministic error codes

- `INVALID_PLUGIN_KEY` - plugin key is empty or contains unsupported characters
- `INVALID_INPUT` - invalid enabled flag / invalid payload
- `STATE_STORE_NOT_CONFIGURED` - no safe default location could be determined
- `STATE_STORE_PATH_INVALID` - store path is a directory
- `STATE_STORE_CORRUPT` - store file is unreadable or invalid
- `STATE_STORE_UNSUPPORTED_SCHEMA` - store schema version mismatch
- `STATE_STORE_IO` - filesystem read/write failures

## Tests

```bash
python -m pytest -q tests/prompt_pack/test_p101_plugin_enable_and_disable_state_store.py
python -m pytest -q tests/test_cli_parity_commands.py -k "plugins"
```
