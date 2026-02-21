# P063 - Message poll create command

This implements **Thomas-native** behavior for prompt-pack item **P063 (Message poll create command)**.

The command creates a poll payload, formats it as a readable message, and can **optionally**
deliver it to a configured webhook endpoint.

## CLI

File:
- `thomas/cli/commands/messages/p063_message_poll_create_command.py`

The surrounding Thomas CLI may mount it under a hierarchy like `message poll create`.

### Examples

Create a poll locally (no external delivery):

```bash
thomas message poll create --question "Where should we eat?" --option "Tacos" --option "Pho" --json
```

Create and deliver (requires webhook configuration):

```bash
thomas message poll create --channel discord --target channel:123 \
  --question "Ship it?" --option "Yes" --option "No" \
  --send --webhook-url "https://…" --json
```

## Input contract

Core input type:
- `thomas.messages.p063_message_poll_create_command.MessagePollCreateInput`

Key fields:
- `question` (str, required)
- `options` (tuple[str, ...], required, 2–10 unique non-empty options)
- `channel` (str | None) - provider/adapter identifier
- `target` (str | None) - destination identifier within the provider
- `allow_multiple` (bool)
- `anonymous` (bool)
- `expires_in_seconds` (int | None)
- `send` (bool)
- `webhook_url` (str | None)
- `base_url` (str | None)
- `metadata` (mapping | None)

## Output contract

Core output type:
- `thomas.messages.p063_message_poll_create_command.MessagePollCreateOutput`

CLI `--json` success:

```json
{
  "ok": true,
  "poll": {
    "poll_id": "…",
    "question": "…",
    "options": ["…"],
    "channel": null,
    "target": null,
    "allow_multiple": false,
    "anonymous": false,
    "expires_at": null,
    "message_text": "…",
    "sent": false,
    "delivery": null,
    "poll_url": null
  }
}
```

CLI `--json` failure:

```json
{
  "ok": false,
  "error": {
    "code": "invalid_input | missing_config | external_failure | internal_error",
    "message": "…",
    "details": {}
  }
}
```

## Deterministic error policy

- **invalid_input** – question/options/channel/target validation fails
- **missing_config** – `--send` requested but no webhook URL provided or configured
- **external_failure** – webhook delivery errors or non-2xx responses
- **internal_error** – unexpected validation failure (should be rare)

## Notes

This implementation intentionally does **not** assume a specific messaging provider (Slack/Teams/etc.).
The webhook payload contains both a user-readable `text` field and a structured `thomas.kind=message_poll`
object for downstream automation.
