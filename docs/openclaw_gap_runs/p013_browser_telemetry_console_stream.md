# P013 — Browser telemetry console stream

This gap run adds a Thomas-native implementation for **streaming browser console messages** from an existing live browser session.

## What it does

- Connects to a running browser via a Chrome DevTools Protocol (CDP) endpoint.
- Streams console events (`log`, `warning`, `error`, etc.) for a bounded duration.
- Supports optional filtering by console level/type.
- Supports machine-readable JSON output for automation.

## CLI

Command:

- `p013-browser-telemetry-console-stream`

Key flags:

- `--cdp-url` — CDP websocket URL (or set `THOMAS_BROWSER_CDP_URL`)
- `--duration` — listen window in seconds
- `--max-events` — safety cap
- `--levels` — filter console types (comma-separated)
- `--json` — JSON output
- `--json-schema` — prints output schema

## Deterministic errors

- `invalid_input` — input validation failure
- `browser_endpoint_missing` — no CDP endpoint configured
- `browser_connection_failed` — could not connect to the live browser
- `no_pages` — connected but there are no pages to observe
