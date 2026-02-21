# P026 - Browser integration into top-level CLI

This change adds a **top-level** `browser` route to the Thomas CLI.

The goal is simple: expose a stable `thomas browser <url>` command that can be used
interactively *and* from automation via deterministic `--json` output.

## Usage

```bash
thomas browser example.com
thomas browser https://example.com
thomas browser open https://example.com
```

### Machine-readable output

```bash
thomas browser https://example.com --json
```

Print the JSON schema for the `--json` output:

```bash
thomas browser --json-schema
```

### Validation-only mode

```bash
thomas browser example.com --dry-run --json
```

## Behavior

Backend selection is best-effort:

1. If the Thomas browser tool is available (`thomas.tools.browser`), it will be used first.
2. Otherwise, it falls back to Python's standard `webbrowser` module.

## Errors & exit codes

Errors are deterministic in `--json` mode via `error.kind`:

- `invalid_input` – malformed URL or invalid arguments
- `missing_config` – `--config` points to a file that does not exist
- `external_failure` – backend failed to open the URL
- `internal_error` – unexpected failure

Stable exit codes:

- `0` success
- `2` invalid input / missing config
- `1` external failure / internal error
