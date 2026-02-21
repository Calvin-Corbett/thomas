# P011 - Browser artifact DOM snapshot

This prompt adds a **Thomas-native** DOM snapshot artifact capture.

## What it does

- Captures a snapshot of the active browser's DOM (best effort):
  - Prefers Chrome DevTools Protocol (CDP) `DOMSnapshot.captureSnapshot` when available.
  - Falls back to raw HTML (`page.content()` / `document.documentElement.outerHTML`) when CDP is unavailable.
- Writes the result to an artifact file:
  - `.json` for CDP/method snapshots
  - `.html` for HTML fallback
- Supports a machine-readable output mode for automation via `--json`.

## CLI

Command name (under the `browser` command group):

- `artifact-dom-snapshot`

Options:

- `--artifacts-dir PATH` — write artifact into a specific directory (overrides config/env)
- `--output PATH` — explicit output file path (takes precedence over `--artifacts-dir`)
- `--base-name TEXT` — filename base for generated artifact names
- `--prefer-cdp / --no-prefer-cdp`
- `--timeout-ms N`
- `--json` — emit a single JSON object

### JSON output

Success:

```json
{
  "ok": true,
  "artifact_path": "...",
  "bytes_written": 1234,
  "content_type": "application/json",
  "capture_method": "cdp",
  "sha256": "..."
}
```

Failure:

```json
{
  "ok": false,
  "error_code": "THOMAS_BROWSER_DOM_SNAPSHOT_MISSING_CONFIG",
  "category": "missing_config",
  "message": "..."
}
```

## Error codes

- `THOMAS_BROWSER_DOM_SNAPSHOT_INVALID_INPUT`
- `THOMAS_BROWSER_DOM_SNAPSHOT_MISSING_CONFIG`
- `THOMAS_BROWSER_DOM_SNAPSHOT_CAPTURE_FAILED`
- `THOMAS_BROWSER_DOM_SNAPSHOT_EXTERNAL_FAILURE`
- `THOMAS_BROWSER_DOM_SNAPSHOT_ASYNC_REQUIRED`
