# P025 - Browser JSON output contract

This change adds a **stable machine-readable output contract** for browser-related CLI commands.

Human-readable output is great for eyeballs and terrible for automation. When scripts need to consume browser results, they need **predictable JSON** with:

- A single JSON object per invocation
- A schema for validation
- Deterministic error codes

## JSON envelope

### Success

```json
{
  "ok": true,
  "data": {
    "stdout": "...",
    "stderr": "...",
    "result": null
  },
  "meta": {
    "contract": "thomas.browser.json_output",
    "contract_version": "1.0",
    "request_id": null,
    "command": "open"
  }
}
```

### Failure

```json
{
  "ok": false,
  "error": {
    "code": "invalid_input",
    "message": "Invalid URL.",
    "details": {
      "url": "..."
    }
  },
  "meta": {
    "contract": "thomas.browser.json_output",
    "contract_version": "1.0",
    "request_id": null,
    "command": "open"
  }
}
```

### Error codes

| Code | Meaning |
|---|---|
| `invalid_input` | Invalid arguments or usage (missing required args, malformed values, etc.) |
| `missing_config` | Required configuration or dependency missing |
| `external_failure` | Failure from external systems (browser engine, network, OS) |
| `internal_error` | Unexpected internal failure (likely a bug) |

## CLI flags

Browser commands support automation flags:

- `--json` – emit machine-readable output (single JSON object).
- `--json-schema` – print the JSON Schema for the JSON envelope and exit.

### Output safety

In `--json` mode, command output is captured and included in the JSON payload as `data.stdout` / `data.stderr`.

If a command writes non-UTF8 bytes to stdout/stderr, the text field is blanked and a lossless copy is provided via:

- `data.stdout_base64`
- `data.stderr_base64`

Logging output is also captured (even for logging handlers configured before `--json` mode starts), preventing stray log lines from corrupting JSON output.

## Implementation layout

- Contract + schema: `thomas/browser/p025_browser_json_output_contract.py`
- CLI patching (Click): `thomas/cli/commands/browser/p025_browser_json_output_contract.py`
- Tests: `tests/prompt_pack/test_p025_browser_json_output_contract.py`
