# P055 - Message edit command

## What this adds

This gap-run implements a **message edit** capability in Thomas:

- A core implementation that validates input and delegates the actual edit to a
  provided editor/client.
- A CLI wrapper that exposes the behavior as a messages subcommand and supports
  a machine-readable `--json` output mode.

## Files

- `thomas/messages/p055_message_edit_command.py`
  - Contracts:
    - `MessageEditCommandInput`
    - `MessageEditCommandOutput`
  - Deterministic error:
    - `MessageEditCommandError` with stable `code` values
  - Entrypoint:
    - `execute_message_edit(request, editor=...)`
  - Optional JSON schemas:
    - `MESSAGE_EDIT_INPUT_SCHEMA`
    - `MESSAGE_EDIT_OUTPUT_SCHEMA`
    - `MESSAGE_EDIT_ERROR_SCHEMA`

- `thomas/cli/commands/messages/p055_message_edit_command.py`
  - CLI registration via `register(subparsers)`
  - Handler via `handle(args, compat=None)`
  - Supports `--json` for automation

## CLI usage

Human-friendly:

```bash
thomas messages edit --id MSG123 --text "Updated text" --channel CHAN9
```

Machine-readable:

```bash
thomas messages edit --json --id MSG123 --text "Updated text"
```

Optional metadata (provider-specific JSON object):

```bash
thomas messages edit --json --id MSG123 --text "Updated text" --metadata '{"reason":"typo"}'
```

## JSON output

Success:

```json
{
  "ok": true,
  "result": {
    "message_id": "MSG123",
    "new_text": "Updated text",
    "channel_id": "CHAN9",
    "edited": true,
    "provider_result": {"...": "..."}
  }
}
```

Failure:

```json
{
  "ok": false,
  "error": {
    "code": "invalid_input | missing_config | external_failure",
    "message": "...",
    "details": {"...": "..."}
  }
}
```

## Tests

Primary acceptance checks:

```bash
python -m pytest -q tests/prompt_pack/test_p055_message_edit_command.py
python -m pytest -q tests/test_cli_parity_commands.py -k "message"
```
