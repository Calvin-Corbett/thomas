# P115 — Plugin gateway handler registry

This run adds a **gateway handler registry** to Thomas.

“Gateway handlers” are the callables that back the Gateway API surface (RPC-ish methods and/or route handlers). The goal is to let **plugins contribute handlers** safely, while giving Thomas a deterministic, inspectable registry (and a CLI hook) to support automation.

## What shipped

### 1) Registry implementation

Module: `thomas.plugins.p115_plugin_gateway_handler_registry`

Key pieces:

- `GatewayHandlerRegistry`
  - In-memory registry with **core-reserved handler names** and **plugin-registered** handlers.
  - Deterministic ordering for listing/snapshots.
  - `register()`, `get()`, `get_spec()`, `list_specs()`, `snapshot()`, `invoke()`.

- Typed contracts
  - `GatewayHandlerSpec` — metadata + optional `input_schema` / `output_schema` for automation.
  - `GatewayHandlerRegistrySnapshot` — machine-readable snapshot payload.
  - `GatewayHandlerRegistryConfig` — minimal config contract for loading handlers from modules.

- Deterministic errors
  - `GatewayHandlerRegistryError` with a stable `code`, `message`, and optional `details`.
  - Covers invalid input, missing config, import/registration failures, and handler exceptions.

### 2) CLI command

Module: `thomas.cli.commands.plugins.p115_plugin_gateway_handler_registry`

Commands:

- `p115-plugin-gateway-handler-registry list`
  - Human-friendly output by default.
  - `--json` outputs a stable JSON payload for scripts/automation.
  - `--config <file.json>` loads plugin modules listed in the config and registers their handlers before listing.

- `p115-plugin-gateway-handler-registry schema`
  - Emits a JSON Schema describing the `list --json` output payload.

## Config format

The loader is intentionally simple: a JSON object with a `plugin_modules` array.

```json
{
  "plugin_modules": [
    "my_project.plugins.some_gateway_plugin",
    "another_plugin"
  ],
  "allow_overrides": false
}
```

Each module can contribute handlers via one of these conventions:

1) A `register_gateway_handlers(registry)` function (preferred)
2) A `GATEWAY_HANDLERS` mapping export:

```py
def ping():
    return "pong"

GATEWAY_HANDLERS = {
    "demo.ping": ping,
    "demo.echo": {"handler": lambda x: x, "description": "Echo input"}
}
```

## Notes

- The registry is dependency-light by design so it can be used from the gateway runtime, the agent, and CLI tooling without bringing in heavyweight imports.
- The `PLUGIN` wrapper is provided for plugin loaders that expect a module-level `register()` entry point.
