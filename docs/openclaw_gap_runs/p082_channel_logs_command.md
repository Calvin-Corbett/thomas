# P082 — Channel logs command

## Summary

Adds a **`channels logs`** subcommand to Thomas.

The command is intended for troubleshooting channel integrations by showing the
most recent **channel-related** log records from the gateway/runtime log file.

Key properties:

- Efficient: tails from the end of the log file (doesn't read the whole file unless needed).
- Robust discovery: supports env var overrides + common config files + common log directories.
- Deterministic failures: standardized error codes and JSON error schema.
- Automation-friendly output: `--json` prints a stable machine-readable payload.

## CLI

```
thomas channels logs [--channel <name|all>] [--lines <n>] [--json]
```

### Options

- `--channel`: Filter by provider (e.g. `telegram`, `discord`) or `all` (default).
- `--lines`: Maximum number of matching records to return (default: 200).
- `--json`: Emit a machine-readable JSON payload.

## Log file discovery

Log file is resolved in the following order:

1. Explicit `log_file` override passed to the domain API (not exposed as a CLI flag here).
2. Environment variables (file or directory):
   - `THOMAS_LOG_FILE`
   - `THOMAS_GATEWAY_LOG_FILE`
   - `THOMAS_LOG_PATH`
3. Config files (best-effort JSON):
   - `~/.thomas/thomas.json`
   - `~/.thomas/config.json`
   - (Windows) `%APPDATA%\thomas\config.json`
4. Conventional log directories (newest file wins):
   - Linux/macOS: `/tmp/thomas/`, `~/.thomas/logs/`
   - Windows: `%TEMP%\thomas\`, `%LOCALAPPDATA%\thomas\logs\`

## Channel record detection

Heuristic rules (best-effort):

- For JSON lines: record is channel-related when `subsystem/logger/name` contains `channels`,
  or when a `channel/provider/integration` field exists.
- For plaintext lines: record is channel-related when it contains `channels/` or starts with `[channels`.

Provider filtering (`--channel != all`) is applied by matching against the same common fields and/or
substring matching in `subsystem/msg/raw`.

## Output contracts

The domain layer returns a `ChannelLogsResult`:

- `channel`
- `log_file`
- `lines_requested`
- `entries[]` where each entry includes `raw` and optional `parsed` JSON mapping.

In JSON mode the CLI prints:

```json
{
  "ok": true,
  "channel": "telegram",
  "log_file": "/tmp/thomas/thomas-2026-02-20.log",
  "lines_requested": 200,
  "lines_returned": 7,
  "entries": [
    {"raw": "...", "parsed": {"ts": "...", "level": "info", "subsystem": "channels/telegram/inbound", "msg": "..."}}
  ]
}
```

On failure (with `--json`), the CLI prints:

```json
{
  "ok": false,
  "error": {"code": "missing_config", "message": "...", "details": {}}
}
```
