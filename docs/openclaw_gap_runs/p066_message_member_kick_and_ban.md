# P066 - Message member kick and ban

This run adds **member moderation** for messaging channels: kicking a member out of a channel (remove) or banning them (prevent re-join), via a configurable outbound webhook.

## What this does

Thomas exposes **Thomas-native** commands (no OpenClaw tool naming):

- `moderate-member --action kick`
- `moderate-member --action ban`

Convenience aliases:

- `kick-member`
- `ban-member`

## Integration seam: outbound webhook

The moderation action calls a webhook URL. Configure it in one of these ways:

1) Pass `--webhook-url` on the CLI, or include `webhook_url` in the JSON payload.
2) Set environment variables:
   - `THOMAS_MESSAGES_MEMBER_MODERATION_WEBHOOK_URL`
   - `THOMAS_MESSAGES_MODERATION_WEBHOOK_URL`
   - `THOMAS_MESSAGES_WEBHOOK_URL`

Optionally, your Thomas config object may expose:

- `messages_member_moderation_webhook_url`
- `messages_moderation_webhook_url`
- `messages_webhook_url`
- `messages_member_moderation_extra_headers` (dict of HTTP headers)

The webhook receives a JSON `POST` like:

```json
{
  "action": "kick",
  "channel_id": "C123",
  "member_id": "U456",
  "reason": "spam",
  "request_id": "trace-123",
  "metadata": {"source": "thomas"}
}
```

Any 2xx response is treated as success. If the response is JSON and contains a `message` field, Thomas surfaces it.

## CLI examples

Human output:

```bash
thomas messages moderate-member --action kick --channel-id C123 --member-id U456 --reason "spam"   --webhook-url https://example.test/moderation
```

Machine output:

```bash
thomas messages moderate-member --action ban --channel-id C123 --member-id U456 --json   --webhook-url https://example.test/moderation
```

Example JSON success:

```json
{
  "ok": true,
  "action": "ban",
  "channel_id": "C123",
  "member_id": "U456",
  "message": "ok",
  "provider_response": {"message": "ok"},
  "request_id": "trace-123"
}
```

Example JSON failure (missing config):

```json
{
  "ok": false,
  "error": {
    "code": "missing_config",
    "message": "No webhook URL configured for member moderation",
    "details": {
      "expected_payload_key": "webhook_url",
      "expected_env": [
        "THOMAS_MESSAGES_MEMBER_MODERATION_WEBHOOK_URL",
        "THOMAS_MESSAGES_MODERATION_WEBHOOK_URL",
        "THOMAS_MESSAGES_WEBHOOK_URL"
      ]
    }
  },
  "request_id": null
}
```
