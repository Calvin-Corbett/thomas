# P014 — Browser telemetry network requests

This gap run adds a Thomas-native implementation for **capturing browser network request telemetry** from an existing live browser session.

## What it does

- Connects to a running browser via a Chrome DevTools Protocol (CDP) endpoint.
- Captures request/response (and request-failed) telemetry for a bounded duration.
- Emits pending requests at the end of the capture window (best-effort).
- Supports optional inclusion of request/response headers and request body (best-effort).
- Supports machine-readable JSON output for automation.

## CLI

Command:

- `p014-browser-telemetry-network-requests`

Key flags:

- `--cdp-url` — CDP websocket URL (or set `THOMAS_BROWSER_CDP_URL`)
- `--duration` — listen window in seconds
- `--max-entries` — safety cap
- `--include-headers` — include request headers
- `--include-post-data` — include request body
- `--include-response-headers` — include response headers
- `--json` — JSON output
- `--json-schema` — prints output schema

## Deterministic errors

- `invalid_input` — input validation failure
- `browser_endpoint_missing` — no CDP endpoint configured
- `browser_connection_failed` — could not connect to the live browser
- `no_pages` — connected but there are no pages to observe
