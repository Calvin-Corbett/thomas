# P059 – Message thread reply

This gap run adds Thomas-native support for replying **inside an existing message thread**.

## Library API

Implementation module:

- `thomas/messages/p059_message_thread_reply.py`

Primary entry point:

- `message_thread_reply(MessageThreadReplyRequest, *, config=None, timeout_s=10.0, http_post=None) -> MessageThreadReplyResult`

### Input

`MessageThreadReplyRequest` fields:

- `thread_id` (str, required): provider thread identifier (e.g., Slack `thread_ts`).
- `text` (str, required): reply text.
- `channel_id` (str, optional): channel/conversation id (required for Slack Web API).
- `provider` (optional): `slack_webhook` or `slack_web_api`.
- `provider_payload` (mapping, optional): provider-specific payload fields (allow-listed per provider).

### Output

`MessageThreadReplyResult.to_dict()` produces a stable, machine-readable JSON shape:

```json
{
  "schema_version": 1,
  "ok": true,
  "provider": "slack_webhook",
  "thread_id": "1234.5678",
  "channel_id": null,
  "message_id": null,
  "text": "hi",
  "raw": {"status_code": 200, "body": "ok"}
}
```

### Deterministic errors

All failures raise `MessageThreadReplyError` subclasses with stable fields:

- `MessageThreadReplyInputError` (`code=invalid_input`)
- `MessageThreadReplyConfigError` (`code=missing_config`)
- `MessageThreadReplyExternalError` (`code=http_error` or `provider_error`)

## CLI

The parity CLI command lives at:

- `thomas/cli/commands/messages/p059_message_thread_reply.py`

### Usage

Slack Incoming Webhooks (simplest; does not require `--channel-id`):

```bash
export THOMAS_SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."
thomas messages thread-reply --thread-id 1234.5678 --text "Replying in a thread"
```

Slack Web API (requires a bot token **and** channel id):

```bash
export THOMAS_SLACK_BOT_TOKEN="xoxb-..."
thomas messages thread-reply --provider slack_web_api --channel-id C0123456789 --thread-id 1234.5678 --text "Replying in a thread"
```

### Provider payload

You can pass allow-listed provider fields as JSON:

```bash
thomas messages thread-reply \
  --thread-id 1234.5678 \
  --text "hi" \
  --provider-payload-json '{"reply_broadcast": true}'
```

Unknown keys are rejected deterministically as `invalid_input`.

### Machine-readable output

Add `--json` to return a stable JSON payload.

Success:

```json
{"ok": true, "result": {"schema_version": 1, "ok": true, "provider": "slack_webhook", "thread_id": "1234.5678", "channel_id": null, "message_id": null, "text": "hi", "raw": {"status_code": 200, "body": "ok"}}}
```

Failure:

```json
{"ok": false, "error": {"code": "missing_config", "message": "...", "details": {}}}
```
