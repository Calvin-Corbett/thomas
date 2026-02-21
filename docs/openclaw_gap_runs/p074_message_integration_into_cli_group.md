# P074 - Message integration into CLI group

This prompt-pack feature adds a Thomas-native `messages` CLI group and wires it
into the root CLI (`thomas.cli.parity_compat`).

## CLI commands

### `thomas messages send`

Sends a message to a configured HTTP webhook.

**Config**
- `THOMAS_MESSAGE_WEBHOOK_URL` (required): Destination URL
- `THOMAS_MESSAGE_TIMEOUT_SECONDS` (optional): Positive float (default 5.0)

**Examples**

Human output:
```bash
thomas messages send "hello" --channel general
```

JSON output (automation-friendly):
```bash
thomas messages send "hello" --channel general --json
```

Metadata:
```bash
thomas messages send "hello" --channel general --meta priority=high --meta trace_id=abc --json
```

## Output schema

Success:
```json
{"ok": true, "result": {"message_id": "...", "channel": "...", "text": "...", "delivered": true, "delivered_at": "...", "provider": "webhook", "response_status": 200}}
```

Failure:
```json
{"ok": false, "error": {"code": "missing_config|invalid_input|delivery_failed", "message": "...", "details": {...}}}
```

## Deterministic exit codes

- 0: Success
- 2: Invalid input (`invalid_input`)
- 3: Missing configuration (`missing_config`)
- 4: External delivery failure (`delivery_failed`)
