# P004 - Browser action: type and press

## What it does

Adds a Thomas-native browser action that:

1. Locates an element by selector
2. (Optionally) clicks to focus it
3. Types text (preferring `fill()`, falling back to `type()`)
4. Presses a key (default: `Enter`)

Implementation:

- Action primitive: `thomas/browser/p004_browser_action_type_and_press.py`
- CLI command: `thomas/cli/commands/browser/p004_browser_action_type_and_press.py`

## Deterministic errors

Failures raise `TypeAndPressError` (or emit JSON with `{ok:false, code, message, step}`) with stable codes:

- `INVALID_INPUT` — invalid parameters
- `MISSING_BROWSER` — no page/browser object provided
- `INVALID_TARGET` — target object is not Playwright-like
- `MISSING_CONFIG` / `CONFIG_INVALID` — could not resolve a live browser/page
- `TIMEOUT` — Playwright timeout
- `EXTERNAL_FAILURE` — any other Playwright/external exception

## CLI usage

Print schemas:

```bash
thomas browser type-and-press --schema
```

Execute with human output:

```bash
thomas browser type-and-press --url https://example.com --selector "#q" --text "hello"
```

Execute with machine output:

```bash
thomas browser type-and-press --selector "#q" --text "hello" --json
```

### Browser resolution

The CLI attempts, in order:

1. Thomas live browser modules (`thomas.cli.live_browser`, `thomas.tools.browser`)
2. `THOMAS_BROWSER_WS_ENDPOINT` (Playwright connect)
3. Local headless launch (requires `--url`)
