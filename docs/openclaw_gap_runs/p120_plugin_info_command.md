# P120 - Plugin info command

This doc captures the expected behavior for the **Thomas** CLI command:

```bash
thomas plugins info <plugin-id> [--json]
```

## Purpose

Show detailed metadata about a single plugin (loaded/disabled/error), including
the tools it exposes and other integration surface area.

## Human output

Without `--json`, the command prints a readable, multi-line summary, including:

- status / version / source / origin (when present)
- registered tools, hooks, gateway methods, providers, CLI commands, services (when present)
- error details (when present)
- install metadata (best-effort, when available from config)

## Machine-readable output

With `--json`, the command emits the plugin record as JSON to stdout.

Example:

```bash
thomas plugins info demo --json
```

Output:

```json
{
  "id": "demo",
  "name": "demo",
  "status": "loaded",
  "toolNames": ["tool.a", "tool.b"]
}
```

## Error behavior

Errors are deterministic and exit non-zero (code `1`), with a concise message on stderr.

Common cases:

- `Plugin not found: <id>`
- `Plugin id is required.`
- Missing/invalid configuration needed to inspect plugins
