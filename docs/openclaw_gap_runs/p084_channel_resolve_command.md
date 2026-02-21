# P084 Channel resolve command

This gap run adds a **Thomas-native** `channels resolve` CLI operation.

The purpose of the command is to take a human-friendly channel reference (or a configured alias)
and resolve it into a **canonical channel identity** that Thomas can use for routing messages.

## CLI

### Human output

```bash
thomas channels resolve @mychannel
```

Example output (shape may vary slightly by integration):

```text
Integration: telegram
Channel ID:  -1001234567890
Username:   @mychannel
Title:      My Channel
Kind:       channel
Reference:  telegram:@mychannel
```

### JSON output (automation)

```bash
thomas channels resolve @mychannel --json
```

Example:

```json
{
  "ok": true,
  "result": {
    "integration": "telegram",
    "channel_id": "-1001234567890",
    "raw_reference": "@mychannel",
    "normalized_reference": "telegram:@mychannel",
    "resolved_via": "external",
    "title": "My Channel",
    "username": "@mychannel",
    "kind": "channel",
    "metadata": {
      "id": -1001234567890,
      "title": "My Channel",
      "type": "channel",
      "username": "mychannel"
    }
  }
}
```

### JSON schema

```bash
thomas channels resolve --json-schema
```

## Configuration

The resolver supports config-based aliases when a configuration object provides a `channels` mapping.

Example conceptual config shape:

```yaml
channels:
  alerts: "telegram:@alerts_channel"
  ops:
    telegram: "@ops_room"
```

## Error handling

Errors are deterministic and include a stable machine-readable `code`:

- `INVALID_INPUT` (exit code 2)
- `MISSING_CONFIG` (exit code 3)
- `EXTERNAL_FAILURE` (exit code 4)
