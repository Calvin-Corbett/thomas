# P005 - Browser action hover and focus

This gap run adds **two element interaction actions** to Thomas' browser stack:

- `hover` — move the pointer over a target element.
- `focus` — move keyboard focus to a target element.

## CLI

These actions are exposed under the existing browser command group:

```bash
thomas browser hover  --selector "#login"
thomas browser focus  --selector "input[name=email]"
```

Targets may be provided as either:

- `--selector` (string)
- `--node-id` (string/int, depending on the node listing backend)

Exactly one target must be provided.

### Machine output

Both commands support `--json` for automation:

```bash
thomas browser hover --selector "#login" --json
```

Success payload:

```json
{
  "ok": true,
  "action": "hover",
  "target": {"selector": "#login"},
  "backend_call": "browser.hover"
}
```

Failure payload:

```json
{
  "ok": false,
  "action": "hover",
  "error": {"code": "invalid_input", "message": "..."}
}
```

## Implementation notes

- The implementation is **backend-agnostic** and uses duck-typing to call `hover` / `focus` on the active browser controller.
- Errors are intentionally deterministic:
  - `invalid_input` for malformed requests
  - `missing_config` if no browser/controller is available
  - `external_failure` for browser backend failures
