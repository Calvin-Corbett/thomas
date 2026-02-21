# P118 - Plugin diagnostics collector

This adds a Thomas-native **plugin diagnostics collector** that can:

- enumerate plugins in `thomas.plugins`
- attempt to import each plugin module (capturing failures)
- optionally correlate plugins with tool registry entries
- emit stable, machine-readable JSON for automation

## CLI

Registered under the `plugins` CLI group:

```bash
thomas plugins p118-plugin-diagnostics-collector
```

Filter to one or more plugins:

```bash
thomas plugins p118-plugin-diagnostics-collector --plugin p118_plugin_diagnostics_collector
```

Disable tool correlation (faster / fewer dependencies):

```bash
thomas plugins p118-plugin-diagnostics-collector --no-include-tools
```

### Machine-readable JSON

```bash
thomas plugins p118-plugin-diagnostics-collector --json
```

On success, JSON includes:

- `ok`: overall success boolean
- `plugins[]`: per-plugin status (loaded/error) and `tool_names` if enabled
- `issues[]`: structured issues (deterministic codes)

On deterministic failure (e.g., unknown plugin), JSON includes:

- `ok: false`
- `error: { code, message, details }`

## Programmatic API

Module:

- `thomas.plugins.p118_plugin_diagnostics_collector`

Entry points:

- `collect_plugin_diagnostics(PluginDiagnosticsInput) -> PluginDiagnosticsReport`
- `tool(input_dict) -> output_dict`

Automation schemas:

- `INPUT_SCHEMA`
- `OUTPUT_SCHEMA`
