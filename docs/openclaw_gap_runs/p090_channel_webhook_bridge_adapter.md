# Channel webhook bridge adapter

This gap run adds a **webhook bridge channel adapter** to Thomas.

The idea is simple: lots of external systems expose **incoming webhooks**. This adapter lets Thomas deliver a JSON payload to any `http(s)` endpoint.

## What it is

- **Outbound bridge**: send a JSON payload to a configured webhook URL.
- **Dependency-light**: implemented with the Python standard library (`urllib`).
- **Deterministic errors**: invalid input/config and request failures are reported with stable error codes.
- **Automation friendly**: supports `--json` output and prints a JSON Schema (`--schema`).

## Payload contract

Default payload schema (see `--schema`):

- `text` (string, required by default CLI mode): message text
- `metadata` (object, optional): any additional structured metadata

Note: the underlying adapter supports *any* JSON-object payload; the CLI enforces `text` unless you pass `--payload-only`.

## CLI usage

Registered names:

- `channels channel-webhook-bridge-adapter` (canonical)
- aliases: `channels webhook-bridge-adapter`, `channels webhook-bridge`

Examples:

```bash
# Send simple text
thomas channels channel-webhook-bridge-adapter \
  --url https://example.com/my-webhook \
  "Hello from Thomas"

# Send structured payload (optionally with text merged in)
thomas channels channel-webhook-bridge-adapter \
  --url https://example.com/my-webhook \
  --payload-json '{"text":"Hello","metadata":{"severity":"info"}}'

# Expert mode: arbitrary payload (no 'text' requirement)
thomas channels channel-webhook-bridge-adapter \
  --url https://example.com/my-webhook \
  --payload-only \
  --payload-json '{"event":"heartbeat","ts":1234567890}'

# Machine readable output
thomas channels channel-webhook-bridge-adapter \
  --url https://example.com/my-webhook \
  --json \
  "Hello"

# Print JSON schema for the default payload
thomas channels channel-webhook-bridge-adapter --schema
```

## Environment variables

- `THOMAS_WEBHOOK_BRIDGE_URL`: default destination URL if `--url` is omitted.

## Error codes

- `missing_config`: required config not provided (e.g., URL)
- `invalid_url`: URL is not http(s)
- `invalid_method`: unsupported HTTP method
- `invalid_payload` / `invalid_payload_json`: payload is missing/invalid
- `invalid_header`: header format invalid
- `invalid_headers`: header mapping invalid
- `invalid_timeout`: timeout invalid
- `request_failed`: network/transport failure
- `non_success_status`: webhook returned a non-2xx status

## Notes

- Any non-2xx response is treated as failure.
- Response body is capped to 500 chars in error details for determinism.
