# P111: Tool completion plugin hook (after-tool)

This run adds a **tool-completion hook** that fires *after* a tool finishes executing.

In Thomas terms: a plugin can observe (and optionally persist) the tool name, input, output, and error **once the tool call is complete**. This is useful for auditing, tracing, telemetry, or building post-processing behaviors that should not live inside individual tools.

## What was added

- `ToolCompletionAuditPlugin` in `thomas/plugins/p111_plugin_hook_after_tool.py`
  - Primary hook method: `on_tool_completed(...)`
  - Compatibility aliases: `after_tool(...)`, `after_tool_call(...)`, `on_tool_result(...)`
  - Optional JSONL logging via `log_path`
- CLI demo command: `p111-plugin-hook-after-tool`
  - Supports `--json` output for automation
  - Supports `--json-schema` for machine-readable schema

## CLI usage

Human-readable:

```bash
thomas plugins p111-plugin-hook-after-tool --tool echo --input '{"hello": "world"}'
```

Machine-readable:

```bash
thomas plugins p111-plugin-hook-after-tool --tool echo --input '{"hello": "world"}' --json
```

Print output schema (useful for automation / gateways):

```bash
thomas plugins p111-plugin-hook-after-tool --json-schema
```

## Logging configuration (JSON file)

Create a JSON config file:

```json
{
  "log_path": "tool_audit.jsonl",
  "include_input": true,
  "include_output": true
}
```

Then run:

```bash
thomas plugins p111-plugin-hook-after-tool --tool echo --input '{"x": 1}' --config tool_audit_config.json
```

Each tool completion is appended as a single JSON line to `tool_audit.jsonl`.
