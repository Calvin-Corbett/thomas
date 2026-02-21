# P061 — Message unpin command

This gap run adds a **Thomas-native** command for **unpinning a message** in a channel.

Implementation:

- Core command: `thomas/messages/p061_message_unpin_command.py`
- CLI surface: `thomas/cli/commands/messages/p061_message_unpin_command.py`

## Behavior

Inputs:

- `channel_id` + `message_id`, or
- `message_url` (Slack & Discord URL formats are parsed when possible)

Notes:

- For Slack permalinks, `p1712345678000100` is converted to `1712345678.000100`.
- If you pass a Slack-style digit timestamp directly as `--message` and the channel id looks Slack-ish,
  it is also coerced to the dotted form.

The command delegates to the configured messaging backend client. It supports multiple backend shapes
(e.g. a Thomas-native `unpin_message`, or Slack SDK `pins_remove`).

## CLI usage

```bash
thomas message unpin --channel C123 --message 1712345678.000100
```

Machine-readable output:

```bash
thomas message unpin --channel C123 --message 1712345678.000100 --json
```

Example JSON success payload:

```json
{"ok": true, "result": {"unpinned": true, "channel_id": "C123", "message_id": "1712345678.000100"}}
```

Example JSON error payload:

```json
{"ok": false, "error": {"code": "message_unpin.external_failure", "message": "..."}}
```

## Input / output contracts

The command exposes lightweight JSON schemas for automation:

- `input_json_schema()`
- `output_json_schema()`

These are intentionally minimal and stable.
