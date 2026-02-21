# P056 - Message delete command

This gap run adds **message deletion** as a Thomas-native command surface.

The implementation is deliberately backend-agnostic: it exposes a stable request/response
contract and defers actual deletion to the configured Thomas messaging backend.

## CLI surface

- Command: `message delete`
- Flags:
  - `--target <id>` / `--to <id>`: provider-specific target (channel/user/etc)
  - `--message-id <id>`: provider message identifier to delete
  - `--channel <name>`: required when multiple providers are configured
  - `--account <id>`: optional multi-account selector
  - `--dry-run`: validate inputs without performing deletion
  - `--json`: machine-readable output

## Output contract (`--json`)

```json
{
  "channel": "slack",
  "account": null,
  "to": "channel:C0123",
  "messageId": "1700000000.000000",
  "deleted": true,
  "dryRun": false
}
```

## Webhook/route contract

Request JSON schema is exported as `REQUEST_SCHEMA` and response schema as `RESPONSE_SCHEMA`.
The server entrypoint is `handle_webhook(payload, **context)` (also aliased as `handle` and
`execute` for dispatcher compatibility).

## Failure modes

Failures are deterministic and keyed by `code`:

- `invalid_input`: required fields missing/invalid
- `config_missing`: no backend configured for deletion
- `external_failure`: provider/backend raised an unexpected error
