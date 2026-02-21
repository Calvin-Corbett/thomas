# P018 - Browser tab management

This adds **tab management** as a first-class Thomas capability.

## What it does

- List open tabs
- Open a new tab (optionally activate it)
- Activate a tab (by id or index)
- Close a tab (by id or index)
- Close all tabs
- Close all other tabs (keep one)

## Architecture

- Core behavior: `thomas/browser/p018_browser_tab_management.py`
  - Backend-agnostic `TabBackend` protocol
  - Deterministic errors for automation and CLI parity tests
  - Includes a small in-memory backend used by unit tests
  - Includes a Playwright-like backend adapter (duck-typed, no Playwright import)

- CLI wrapper: `thomas/cli/commands/browser/p018_browser_tab_management.py`
  - Supports both argparse-style registration (`build_parser`) and Typer-style (`app`)
  - JSON output mode: `--json`

## Automation output (JSON)

### Success

```json
{
  "ok": true,
  "action": "list",
  "tabs": [
    { "id": "tab-1", "index": 0, "url": "https://example.com", "title": null, "active": true }
  ],
  "affected_tab": null,
  "closed_tab_ids": []
}
```

### Failure

```json
{
  "ok": false,
  "error": {
    "code": "missing_config",
    "message": "No browser tab backend is configured.",
    "details": { "hint": "..." }
  }
}
```
