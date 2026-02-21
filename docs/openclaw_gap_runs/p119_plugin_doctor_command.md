# P119 — Plugin doctor command

This adds a **plugin diagnostics** capability to Thomas.

The intent is to answer a boring but important question:

> “Are my plugins importable, and do they still wire into the ToolRegistry surface the way Thomas expects?”

## CLI

The command is exposed under the `plugins` command group:

```bash
thomas plugins doctor
```

Options:

```bash
# Inspect everything under thomas.plugins
thomas plugins doctor

# Inspect one specific plugin module (short name under thomas.plugins)
thomas plugins doctor --plugin p119_plugin_doctor_command

# Validate that a config file exists (fails deterministically if missing)
thomas plugins doctor --config ./thomas.toml

# Treat warnings as failures
thomas plugins doctor --strict

# Emit machine-readable output
thomas plugins doctor --json
```

Exit codes:

- `0` — No failures detected
- `1` — Failures detected in the report
- `2` — Deterministic user/config error (invalid input, missing config path, unsupported registry interface)

## Machine-readable output

`--json` returns a stable structure:

```json
{
  "ok": true,
  "inspected": ["thomas.plugins.some_plugin", "..."],
  "checks": [
    {
      "id": "core-import:thomas.tools.registry",
      "status": "pass",
      "summary": "import ok",
      "details": {}
    }
  ]
}
```

Deterministic errors (invalid input / missing config path) use a different JSON shape at the CLI boundary:

```json
{
  "ok": false,
  "error": {
    "code": "INVALID_INPUT",
    "message": "..."
  }
}
```

## What the doctor checks

The diagnostics are intentionally conservative and deterministic:

- Core Thomas imports (`thomas.autonomy.plugin`, `thomas.tools.registry`, `thomas.agent.loop`)
- Plugin discovery under `thomas.plugins`
- Per-plugin importability
- Best-effort detection + execution of a registration hook:
  - `register(registry)` on the module, or
  - `plugin.register(registry)` / `PLUGIN.register(registry)`
- Basic registry wiring validation via a probe registry:
  - tool names must be strings
  - tool callables must be callable
  - duplicate tool names are flagged
  - cross-plugin tool name collisions are flagged

## Gateway API usage

The underlying tool implementation lives in:

- `thomas.plugins.p119_plugin_doctor_command.run_plugin_doctor`

It uses explicit request/response contracts (`PluginDoctorRequest`, `PluginDoctorReport`) and is designed
to be serializable via `.to_dict()` for Gateway-style integrations.
