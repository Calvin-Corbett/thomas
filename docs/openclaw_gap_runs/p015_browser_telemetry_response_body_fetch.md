# P015 - Browser telemetry response body fetch

## What this adds

Thomas gains a **browser telemetry response body fetch** primitive: given a telemetry
request/response identifier (commonly a Chrome DevTools Protocol `requestId`), Thomas can
ask the active browser backend for the corresponding response body.

This is handy when you're recording network telemetry and want to inspect or persist
the payload of a specific response (e.g., JSON API calls).

## Thomas-native surface area

### Core API

Module: `thomas.browser.p015_browser_telemetry_response_body_fetch`

**Input**: `BrowserTelemetryResponseBodyFetchRequest`

- `request_id` (str, required): telemetry request/response identifier
- `max_bytes` (int, optional): truncate returned body to at most this many bytes
- `timeout_s` (float, optional): backend fetch timeout in seconds

**Output**: `BrowserTelemetryResponseBodyFetchResult`

- `body_base64` (str): base64-encoded bytes of the response body (always present)
- `body_text` (str | None): UTF-8 decoded body when possible
- metadata: `content_type`, `url`, `status`
- sizes/flags: `original_size_bytes`, `returned_size_bytes`, `truncated`,
  `original_base64_encoded`

**Deterministic errors** raise `BrowserTelemetryResponseBodyFetchError` with stable `code`:

- `invalid_input`
- `missing_config`
- `unsupported_backend`
- `external_failure`
- `invalid_context`

> If you're inside an async event loop and your backend is async, use
> `async_fetch_browser_telemetry_response_body()`.

### CLI

Command (under `browser`): `telemetry-response-body-fetch`

Examples:

```bash
thomas browser telemetry-response-body-fetch <request-id>
thomas browser telemetry-response-body-fetch <request-id> --max-bytes 65536
thomas browser telemetry-response-body-fetch <request-id> --timeout 5
thomas browser telemetry-response-body-fetch <request-id> --json
```

#### Machine-readable output (`--json`)

Success:

```json
{
  "ok": true,
  "result": {
    "request_id": "…",
    "body_base64": "…",
    "body_text": "…",
    "content_type": "…",
    "url": "…",
    "status": 200,
    "original_size_bytes": 1234,
    "returned_size_bytes": 1234,
    "truncated": false,
    "original_base64_encoded": false
  }
}
```

Failure:

```json
{
  "ok": false,
  "error": {
    "code": "missing_config",
    "message": "No browser backend is configured or running.",
    "details": { "attempted": ["…"] }
  }
}
```

## Notes on implementation

- Backend discovery is best-effort: Thomas will try to resolve an existing running
  browser via `thomas.cli.live_browser`, then fall back to `thomas.tools.browser`.
- Returned bodies are always available as base64 bytes; a UTF-8 decoded `body_text`
  is provided when possible.
