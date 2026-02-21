# P034 - Node command restart

## Summary

Thomas now supports restarting the **local node host service** via a dedicated Thomas-native implementation.

* Core behavior lives in `thomas/nodes/p034_node_command_restart.py`.
* CLI behavior lives in `thomas/cli/commands/nodes/p034_node_command_restart.py`.
* The CLI supports machine-readable output via `--json`.

## Behavior

1. Reads the node host configuration (`node.json`) from the Thomas state directory.
2. Resolves the service name:
   * explicit `--service-name` override wins
   * then config (`serviceName` / `nodeHost.serviceName`)
   * then fallback `thomas-node`
3. Determines the service manager:
   * explicit `--manager` override wins
   * then config (`manager` / `nodeHost.manager`)
   * then platform default (Linux→systemd, macOS→launchd, Windows→windows)
4. Executes a restart using the chosen manager.

### Service-manager commands

* Linux (systemd user units):
  * `systemctl --user restart <service>`
* macOS (launchd):
  * `launchctl kickstart -k gui/<uid>/<label>`
  * If `service_name` already contains `/` it is treated as fully-qualified.
* Windows:
  * Primary: PowerShell `Restart-Service -Name '<service>' -Force`
  * Fallback: `sc stop <service>` then `sc start <service>`

## Error handling

Failures raise `NodeRestartError` with deterministic `code` values:

* `missing_config` — node host is not installed/configured (no `node.json`)
* `invalid_config` — config exists but is unreadable/invalid JSON
* `invalid_input` — request fields are invalid (e.g., non-positive timeout)
* `external_failure` — service manager invocation failed
* `unsupported_platform` — platform/service manager cannot be determined

## Automation output (`--json`)

The CLI emits **one JSON object** to stdout.

### Success

```json
{
  "ok": true,
  "result": {
    "ok": true,
    "service_name": "thomas-node",
    "manager": "systemd",
    "steps": [
      {
        "command": ["systemctl", "--user", "restart", "thomas-node"],
        "returncode": 0,
        "stdout": "",
        "stderr": ""
      }
    ],
    "started_at_s": 1700000000.0,
    "finished_at_s": 1700000000.1,
    "meta": {"config_path": "..."}
  }
}
```

### Failure

```json
{
  "ok": false,
  "error": {
    "code": "missing_config",
    "message": "Node host is not configured. Run `thomas nodes install` first.",
    "details": {"config_path": "..."}
  }
}
```
