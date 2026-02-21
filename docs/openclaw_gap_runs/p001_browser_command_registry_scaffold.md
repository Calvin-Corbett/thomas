# P001 Browser command registry scaffold

This change introduces a **Thomas-native** browser command registry scaffold:

- A small runtime registry for **describing** browser-related commands.
- Deterministic, machine-readable error payloads.
- A CLI surface for printing the registry in human or JSON form.

The goal is to provide a stable contract that browser tooling and higher-level
automation can build upon without coupling directly to one concrete browser
driver.

## Discovery behavior

`build_browser_command_registry_scaffold()` always registers a small set of safe
meta-commands:

- `registry.list`
- `registry.describe`
- `session.ping`

If `thomas.tools.browser` is importable, it then performs a **best-effort**
discovery pass that attempts to extract additional command definitions from
common structures (`COMMANDS`, `ROUTES`, `ACTIONS`, etc.).

Discovery failures are swallowed so the scaffold remains usable even when
optional browser dependencies are missing.

## New modules

- `thomas/browser/p001_browser_command_registry_scaffold.py`
  - Core registry (`BrowserCommandRegistry`) and contracts
  - Deterministic error classes + payloads
  - Discovery helpers
  - `build_browser_command_registry_scaffold()` builds a minimal, safe registry

- `thomas/cli/commands/browser/p001_browser_command_registry_scaffold.py`
  - Argparse-compatible registration hook for a new subcommand:
    - `thomas browser registry`
    - `thomas browser commands` (alias)

## CLI usage

Human-readable output:

```bash
thomas browser registry
```

Machine-readable output:

```bash
thomas browser registry --json
```

JSON schema for automation:

```bash
thomas browser registry --schema
```

## Output contracts

### `--json`

```json
{
  "ok": true,
  "registry": {
    "name": "thomas.browser",
    "version": 1,
    "commands": [
      {
        "name": "registry.list",
        "description": "List available browser commands.",
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object"}
      }
    ]
  }
}
```

Failures are deterministic and return `ok=false` with an `error` payload:

```json
{
  "ok": false,
  "error": {
    "code": "missing_config",
    "message": "Missing required browser configuration",
    "details": {}
  }
}
```

### `--schema`

Emits JSON schema describing the `--json` payload (`output`) and the registry
body (`registry`).
