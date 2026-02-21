# P106 - Plugin command registry bridge

## What this adds

Thomas has two adjacent concepts:

- **Plugin commands**: callable units registered by plugins (often operational tasks or integrations)
- **Tools**: callable units exposed to agents (and typically to the gateway layer) with JSON-friendly input/output

This change adds a **bridge** so plugin commands can be invoked through the tool interface without turning
every plugin command into a separate tool.

Instead, we expose one bridge tool (`plugins.invoke`) that dispatches to the plugin command registry by name.

## Public contracts

### Request

```json
{
  "command": "string",
  "args": {"any": "json"}
}
```

- `command`: required, non-empty string
- `args`: required object (may be empty)

### Response

Success:

```json
{
  "ok": true,
  "command": "string",
  "result": {},
  "error": null
}
```

Failure:

```json
{
  "ok": false,
  "command": "string | null",
  "result": null,
  "error": {
    "code": "...",
    "message": "...",
    "details": {"optional": "..."}
  }
}
```

### Stable error codes

- `INVALID_INPUT`: payload shape/type doesn't match the request contract, or args don't fit the command signature
- `MISSING_CONFIG`: no command registry available
- `COMMAND_NOT_FOUND`: `command` is not registered
- `INVALID_COMMAND`: registry returned a non-invokable object
- `UNSUPPORTED_REGISTRY`: tool registry couldn't accept the bridge tool
- `EXTERNAL_FAILURE`: the command raised or otherwise failed during execution

## CLI support

A matching CLI command is provided for diagnostics and automation:

- `plugin-command-registry-bridge --schema --json`
  - emits machine-readable JSON schemas for request/response
- `plugin-command-registry-bridge --list --json`
  - lists available plugin command names (if a registry can be discovered)
- `plugin-command-registry-bridge --command <name> --args-json '{...}' --json`
  - invokes a plugin command via the bridge

## Integration notes

- The bridge tool can be registered even if the command registry is not available at registration time.
  Missing config becomes a deterministic runtime failure from the bridge tool itself (`MISSING_CONFIG`).
- If the command registry provides a native `invoke(name, **kwargs)` API, the bridge will use it.
  Otherwise it resolves the command object and calls it directly.
