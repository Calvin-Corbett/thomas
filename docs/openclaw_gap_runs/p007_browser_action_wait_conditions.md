# P007 - Browser action wait conditions

This gap run adds **explicit, user-defined wait conditions** that run *after* a browser action.

Why this exists: browser automation is fragile when actions return before the page is in the expected state. Instead of relying on implicit sleeps, Thomas can express *what* must be true before continuing.

## Spec

The command accepts a JSON spec:

```json
{
  "action": {"kind": "click", "selector": "#submit"},
  "waits": [
    {"kind": "load_state", "state": "networkidle", "timeout_ms": 10000},
    {"kind": "selector", "selector": "#success", "state": "visible"},
    {"kind": "timeout", "timeout_ms": 250}
  ],
  "default_timeout_ms": 5000
}
```

### Actions

Supported `action.kind` values:

- `goto` (requires `url`)
- `click` (requires `selector`)
- `fill` (requires `selector` + `text`)
- `press` (requires `selector` + `key`)
- `type` (requires `selector` + `text`)
- `select` (requires `selector` + `text`)

### Wait conditions

Supported `waits[].kind` values:

- `load_state`: wait for page load state (`load`, `domcontentloaded`, `networkidle`)
- `selector`: wait for a selector state (`attached`, `detached`, `visible`, `hidden`)
- `url`: wait for the current URL to match
- `timeout`: wait a number of milliseconds

All waits are applied **in order**. Any missing per-wait `timeout_ms` is filled from `default_timeout_ms`.

## CLI usage

Validate and print a plan (no browser):

```bash
thomas browser p007-browser-action-wait-conditions --spec @spec.json --dry-run
```

Read the spec from stdin:

```bash
cat spec.json | thomas browser p007-browser-action-wait-conditions --spec - --dry-run
```

Machine-readable output:

```bash
thomas browser p007-browser-action-wait-conditions --spec @spec.json --dry-run --json
```

JSON schema for automation:

```bash
thomas browser p007-browser-action-wait-conditions --schema --json
```

## Errors

Errors are deterministic and machine-readable:

- `INVALID_INPUT`: invalid spec
- `MISSING_BROWSER`: execution requested but no browser driver is configured
- `BROWSER_FAILURE`: action or wait failed at runtime
