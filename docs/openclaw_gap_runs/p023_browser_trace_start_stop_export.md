# P023 — Browser trace start / stop / export

This gap run adds **browser tracing controls** to Thomas.

The implementation is "Thomas-native" and uses **Playwright tracing** (the trace ZIP that can be opened in Playwright Trace Viewer).

## What it adds

- `browser trace start` — start capturing a trace on the active browser context
- `browser trace stop` — stop tracing and persist a temporary trace ZIP
- `browser trace export <path>` — export the temporary trace ZIP to a user-defined destination

## Export path behavior (ZIP-first)

- If `<path>` is a **directory**, the trace is exported as:

  `browser_trace_<trace_id>.zip` inside that directory.

- If `<path>` is a **file path without an extension**, `.zip` is appended automatically.

This makes automation more reliable and keeps trace artifacts consistently ZIP-shaped.

## CLI usage

Assuming you have a live browser session context:

```bash
thomas browser trace start
thomas browser trace stop
thomas browser trace export ./artifacts/
```

Machine-readable output mode:

```bash
thomas browser trace start --json
```

Success example:

```json
{"ok": true, "action": "browser_trace_start", "result": {"status": "started", "trace_id": "..."}}
```

Failure example:

```json
{"ok": false, "action": "browser_trace_start", "error": {"code": "BROWSER_TRACE_MISSING_SESSION", "message": "No active browser session found. Run this command from a live browser session context."}}
```

## Deterministic error codes

The core module raises `BrowserTraceError` with stable codes such as:

- `BROWSER_TRACE_MISSING_SESSION`
- `BROWSER_TRACE_TARGET_NOT_TRACEABLE`
- `BROWSER_TRACE_ALREADY_STARTED`
- `BROWSER_TRACE_NOT_STARTED`
- `BROWSER_TRACE_NOT_STOPPED`
- `BROWSER_TRACE_INVALID_EXPORT_PATH`

## Automation hooks

For automation/router layers, the core module exposes JSON Schemas via:

- `input_schemas()`
- `output_schemas()`

These schemas are derived from the explicit dataclass contracts.
