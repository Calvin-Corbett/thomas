# P029 — Node host lifecycle service

This gap-run closes the "local node host lifecycle" slice.

OpenClaw reference behavior (for context only):

- `openclaw node install ...` installs a **user service** that runs a headless node host.
- `openclaw node status|stop|restart|uninstall` manage that service.
- Service management commands accept `--json` for automation.

## Thomas-native behavior

Thomas exposes this as a *nodes* sub-tree command:

- `thomas nodes host install ...`
- `thomas nodes host status`
- `thomas nodes host stop`
- `thomas nodes host restart`
- `thomas nodes host uninstall`

Internally this is implemented as a deterministic, test-friendly lifecycle service:

- Configuration is stored under the Thomas config dir (default `~/.thomas`, overridable via `THOMAS_HOME`).
- Service state is tracked in a JSON state file.
- The implementation deliberately avoids relying on systemd/launchd/Windows Service APIs so that it works consistently in CI and container environments.

## Input contract

Install options map to the following request fields:

- `gateway_host` (string, required; default `127.0.0.1`)
- `gateway_port` (int 1–65535; default `18789`)
- `tls` (bool)
- `tls_fingerprint_sha256` (optional 64 hex chars; `sha256:` prefix accepted)
- `node_id` (optional string)
- `display_name` (optional string)
- `runtime` (string identifier; default `python`)
- `force` (bool)

Validation failures raise a deterministic `NodeHostServiceError` with a stable error code.

## Output contract

All lifecycle commands return a single JSON object when `--json` is set:

```json
{
  "ok": true,
  "action": "install|status|stop|restart|uninstall",
  "message": "...",
  "status": {
    "installed": true,
    "running": true,
    "gateway_host": "127.0.0.1",
    "gateway_port": 18789,
    "tls": false,
    "tls_fingerprint_sha256": null,
    "node_id": null,
    "display_name": null,
    "runtime": "python",
    "config_path": "/home/user/.thomas/node_host.json",
    "state_path": "/home/user/.thomas/node_host_service_state.json",
    "last_action": "install",
    "updated_at": 1700000000.0
  }
}
```

Errors are deterministic and machine-readable:

```json
{
  "ok": false,
  "action": "install",
  "error": {
    "code": "invalid_input|not_installed|already_installed|corrupt_state|external_failure",
    "message": "...",
    "details": {}
  }
}
```

## Tests

- Success path: install → status → stop/restart/uninstall
- Failure path: invalid input (bad port), missing install (stop without install)
- CLI JSON output: success + failure
