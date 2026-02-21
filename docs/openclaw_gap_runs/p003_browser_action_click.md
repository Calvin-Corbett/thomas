# P003 - Browser action click

This note documents the **browser click action** added for the P003 gap run.

## What it does

Thomas now provides a **Thomas-native** click action that:

- Validates a click target (either a **node id** *or* a **CSS selector*).
- Resolves an active browser session when one isn't explicitly provided.
- Performs the click using duck-typed browser client methods (so it can wrap different drivers).
- Supports machine-readable output for automation (`--json`) and JSON schema helpers.

## Code locations

- Action logic: `thomas/browser/p003_browser_action_click.py`
- CLI wiring: `thomas/cli/commands/browser/p003_browser_action_click.py`

## CLI usage

Examples:

```bash
# Click by node id (preferred)
thomas browser click --node-id 12

# Click by selector
thomas browser click --selector "button.submit"

# Convenience: positional target (interprets digits as node id)
thomas browser click 12
thomas browser click "button.submit"

# Machine-readable output
thomas browser click --node-id 12 --json
```

## Automation usage

The action module supports dict/JSON-friendly entry points:

- `run(payload: dict, browser=...) -> dict`
- `input_schema() -> dict` (JSON Schema for request)
- `output_schema() -> dict` (JSON Schema for response)

## Output contract (JSON)

When `--json` is used, the command emits JSON.

Success example:

```json
{"clicked": true, "details": "clicked", "ok": true, "target": {"node_id": 12, "selector": null}, "used": "node_id"}
```

Failure example:

```json
{"clicked": false, "error": {"kind": "invalid_input", "message": "Exactly one of target.node_id or target.selector must be provided"}, "ok": false}
```

## Deterministic errors

Errors are mapped to stable kinds:

- `invalid_input` — malformed request (missing/ambiguous target, invalid timeout)
- `missing_config` — no live browser session could be resolved
- `external_failure` — underlying browser driver raised
