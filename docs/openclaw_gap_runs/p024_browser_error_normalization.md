# P024 — Browser error normalization

## What changed

Browser automation can fail in a bunch of places (input validation, missing
configuration, missing dependencies, local backend issues, networking). Historically
those failures often bubbled up as whatever the underlying layer emitted
(exceptions, nested dicts, partial tracebacks), which makes automation brittle.

This gap-run adds a small normalization layer:

* Library: `thomas.browser.p024_browser_error_normalization.normalize_browser_error`
* CLI helper: `thomas browser normalize-error ... --json`

The implementation is **Thomas-native**: it does not reuse OpenClaw naming or schemas,
but it does recognize common error strings so it can map them to stable error codes.

## Input contract

`BrowserErrorNormalizationRequest` (dataclass):

* `raw`: `Any` (string, exception, dict, list, etc.)
* `operation`: optional string context (e.g., `"snapshot"`, `"click"`)
* `profile`: optional profile name
* `target_url`: optional URL
* `http_status`: optional upstream HTTP status code

## Output contract

`BrowserErrorNormalizationResult` (dataclass):

* `code`: machine-readable stable code (e.g., `browser_control_unreachable`)
* `category`: one of `input | config | external | internal`
* `message`: short human-readable summary
* `retryable`: boolean hint for automation loops
* `raw`: sanitized raw error text (tokens/passwords redacted)
* optional echo-back context (`operation`, `profile`, `target_url`, `http_status`)
* optional `details` dict with stable keys

The result also supports `to_dict()` for JSON serialization.

## Deterministic error handling

The normalizer never raises. Even for invalid input (e.g., `raw=None`) it returns a
stable result (`browser_error_missing`).

## Machine-readable output

The CLI supports:

* `--json` to emit a stable JSON object
* `--schema` to emit a minimal JSON schema for that output

Examples:

```bash
thomas browser normalize-error "Can't reach the browser control service" --json
thomas browser normalize-error '{"error": "Failed to start Chrome CDP"}' --json
thomas browser normalize-error --schema --json
```

When the `error` argument is missing and no stdin is provided, the command exits with
status code `2` (consistent with "bad user input"), but still prints the normalized JSON
payload.
