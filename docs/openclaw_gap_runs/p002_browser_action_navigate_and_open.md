# P002 — Browser Navigate + Open

## Goal

Add Thomas-native support for two essential browser URL operations:

- **Navigate**: move the currently focused tab/page to a URL.
- **Open**: open a URL in a new tab/page.

These are foundational building blocks for higher-level browser workflows.

## Implementation overview

Core behavior:

- `thomas/browser/p002_browser_action_navigate_and_open.py`

It provides:

- Typed contracts:
  - `NavigateAndOpenRequest`
  - `NavigateAndOpenResult`
- Deterministic error types:
  - `InvalidNavigateAndOpenInput`
  - `MissingBrowserConfiguration`
  - `BrowserOperationFailed`
  - `SyncCalledFromAsyncContext`
- Both async and sync entrypoints:
  - `async_p002_navigate_and_open(...)`
  - `run_p002_navigate_and_open(...)`
- A compatibility adapter that can call a variety of likely browser tool APIs:
  - direct methods (`navigate`, `open`, `goto`, `open_tab`, ...)
  - nested tab managers (`browser.tabs.open`)
  - generic executors (`run(payload)` / `execute(payload)`)

### Machine-readable schemas

The module exposes `get_p002_schemas()` returning JSON-schema-like dicts for input/output.

## CLI wiring

CLI commands:

- `browser navigate <url> [--timeout-ms N] [--profile NAME] [--json]`
- `browser open <url> [--timeout-ms N] [--profile NAME] [--json]`

CLI implementation:

- `thomas/cli/commands/browser/p002_browser_action_navigate_and_open.py`

Registration behavior is flexible:

- If `thomas.cli.commands.browser` exposes an `app` (Typer instance), commands attach there.
- Otherwise a fallback `app` is exported for tests/alternate loaders.

### JSON output

Success:

```json
{
  "ok": true,
  "action": "navigate",
  "url": "https://example.com",
  "tab_id": "t1",
  "raw": {"...": "..."}
}
```

Failure:

```json
{
  "ok": false,
  "error": {
    "code": "browser.navigate_open.invalid_input",
    "message": "...",
    "details": {"...": "..."}
  }
}
```

## Tests

- `tests/prompt_pack/test_p002_browser_action_navigate_and_open.py`

Coverage includes:

- Input validation.
- Dispatch to navigate vs open.
- Async browser-method compatibility.
- JSON serialization safety.
- CLI `--json` behavior + exit codes.
