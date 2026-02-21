# P020 - Browser lifecycle: start / stop / restart

This gap run adds Thomas-native browser lifecycle controls that can be used from:
- the Thomas CLI (`thomas browser start|stop|restart`)
- internal orchestration code (via a small, typed Python API)

## What it does

The implementation introduces:

- A small **core API**: `thomas.browser.p020_browser_lifecycle_start_stop_restart`
  - `BrowserLifecycleRequest` input contract
  - `BrowserLifecycleResult` output contract
  - `BrowserLifecycleError` deterministic errors (`code`, `message`, optional `details`)
  - `run_browser_lifecycle()` entrypoint

- A **CLI command module**: `thomas.cli.commands.browser.p020_browser_lifecycle_start_stop_restart`
  - `start`, `stop`, `restart` commands
  - `--json` machine-readable output for automation

The runtime backend is **not hard-coded**. The core API adapts an existing controller from Thomas tooling (preferring `thomas.cli.live_browser`, then `thomas.tools.browser`). If neither is available, the core API raises a deterministic `CONFIG_MISSING` error.

## CLI usage

Human output:

```bash
thomas browser start
thomas browser stop
thomas browser restart
```

Machine-readable output:

```bash
thomas browser start --json
thomas browser stop --json
thomas browser restart --json
```

Example success payload:

```json
{
  "action": "start",
  "details": {"pid": 123},
  "ok": true,
  "state": "running"
}
```

Example failure payload:

```json
{
  "ok": false,
  "error": {
    "code": "CONFIG_MISSING",
    "message": "Browser tooling is not available (missing configuration or dependencies).",
    "details": {}
  }
}
```

## Determinism

For automation and tests, failures are surfaced as `BrowserLifecycleError` with stable codes/messages.
Exceptions coming from external tooling are wrapped into `EXTERNAL_FAILURE` with the exception class name exposed as `details.exception_type`.

## Backend resolution

The core API attempts to adapt one of the following Thomas modules into a minimal controller interface:

1. `thomas.cli.live_browser`
2. `thomas.tools.browser`

It supports common method names like `start/stop/restart`, plus common synonyms (`launch`, `shutdown`, etc.). If a backend exists but does not expose compatible methods, a deterministic `UNSUPPORTED_BACKEND` error is raised.
