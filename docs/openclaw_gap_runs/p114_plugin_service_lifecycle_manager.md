# P114 — Plugin service lifecycle manager

This change adds a **service lifecycle manager** that can **start, stop, restart, and query status** for background services registered by plugins (or core). It is designed to be:

- **Deterministic** (stable ordering + stable error codes)
- **Automation-friendly** (`--json` output + published JSON schemas + `apply` command)
- **Safe to embed** (no auto-start at import time)

## What counts as a “service”?

A service is a lightweight definition with:

- a stable `service_id` string
- a `start()` function (sync or async)
- a `stop()` function (sync or async)

The lifecycle manager owns status tracking (`running` / `stopped` / `failed`) and provides consistent error handling.

## Public contracts

### Request contract

`ServiceLifecycleRequest`:

- `action`: one of `start|stop|restart|status|list`
- `service_id`: required for `start|stop|restart|status`
- `timeout_s`: optional timeout for async start/stop

Machine-readable schema:

- `SERVICE_LIFECYCLE_REQUEST_SCHEMA`

### Response contract

`ServiceLifecycleResponse`:

- `ok`: boolean
- `services`: list of `ServiceStatus`
- `error`: `null` on success; otherwise a deterministic `{code,message,details}` structure

Machine-readable schema:

- `SERVICE_LIFECYCLE_RESPONSE_SCHEMA`

### Error codes

All failures use one of these stable codes:

- `invalid_input`
- `missing_config`
- `external_failure`

## Tool surface (Gateway / registry)

The module exposes a best-effort ToolRegistry-compatible surface:

- Tool name: `plugins.service_lifecycle`
- Input schema: `SERVICE_LIFECYCLE_REQUEST_SCHEMA`
- Output schema: `SERVICE_LIFECYCLE_RESPONSE_SCHEMA`

The plugin entrypoint attempts to register this tool against a registry-like object via duck-typed method discovery (`register_tool`, `register`, etc.) to avoid hard coupling to a single registry API.

## CLI usage

A CLI command group is provided under the plugins command namespace. It expects the host CLI context (`ctx.obj`) to expose a lifecycle manager instance, commonly under:

- `plugin_service_manager`
- `service_manager`
- `services_manager`

### Examples

Human output:

```bash
thomas plugins service-lifecycle status
```

Machine output:

```bash
thomas plugins service-lifecycle status --json
```

Apply arbitrary JSON request (automation-friendly):

```bash
thomas plugins service-lifecycle apply --request '{"action":"start","service_id":"my_service"}' --json
```

Schemas:

```bash
thomas plugins service-lifecycle schema --json
```

## Notes for integrators

The plugin module exports a lightweight plugin entrypoint (`PLUGIN` + `register(api)`), but it does **not** auto-start services. Starting/stopping is an explicit decision by the host runtime (agent loop, gateway, etc.).
