# P083 - Channel capabilities command (Thomas)

## What this adds

A new **channels** subcommand that reports what a configured messaging channel can do, based on the integration implementation.

Thomas-native command:

- `thomas channels capabilities <channel>`

## CLI usage

Human-readable:

```bash
thomas channels capabilities alerts
```

Machine-readable:

```bash
thomas channels capabilities alerts --json
```

## Output contract

### JSON shape

`--json` outputs one JSON object on stdout:

```json
{
  "ok": true,
  "schema_version": 1,
  "channel": "alerts",
  "integration": "telegram",
  "capabilities": {
    "send_text": true,
    "send_image": true,
    "delete_message": false
  },
  "native": null,
  "details": {
    "discovered_callables": ["send_message", "send_photo", "delete_message"]
  }
}
```

### Deterministic errors

On failure with `--json`, stdout receives:

```json
{
  "ok": false,
  "error": {
    "code": "missing_config",
    "message": "No configuration object was provided.",
    "details": {}
  }
}
```

Error codes:

- `invalid_input`
- `missing_config`
- `unknown_channel`
- `unknown_integration`
- `external_failure`
