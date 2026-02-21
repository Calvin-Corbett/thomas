# P113 — Plugin tool provider injection

This GAP run validates that Thomas plugins can *inject a tool provider* into the runtime tool registry, rather than only registering individual tools.

## What this run covers

- A plugin provides a **tool provider** object.
- The provider exposes a demo tool (`p113_echo`) that echoes a `text` input.
- The provider is injected into the registry via a supported registry API (`register_tool_provider`, `register_provider`, `add_tool_provider`, or `add_provider`).
- Errors are deterministic and support machine-readable output (`--json`).

## CLI

> Note: exact top-level wiring depends on your Thomas CLI layout. This module exposes a Typer subcommand named `p113-tool-provider-injection`.

Example:

```bash
thomas plugins p113-tool-provider-injection --provider-id p113.injected --tool-name p113_echo
```

Machine-readable output:

```bash
thomas plugins p113-tool-provider-injection --json
```

Successful JSON output shape:

```json
{
  "ok": true,
  "result": {
    "ok": true,
    "provider_id": "p113.injected",
    "injected_tool_names": ["p113_echo"],
    "error_code": null,
    "error_message": null
  },
  "error": null
}
```

Failure JSON output shape:

```json
{
  "ok": false,
  "result": null,
  "error": {
    "code": "unsupported_registry",
    "message": "Registry does not support tool provider registration. ..."
  }
}
```

## Tests

```bash
python -m pytest -q tests/prompt_pack/test_p113_plugin_tool_provider_injection.py
```
