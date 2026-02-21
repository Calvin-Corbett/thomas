# P032 - Nodes run (Node command run)

This gap-run adds a Thomas-native **`nodes run`** capability: run an OS command on a selected node through the Thomas gateway.

Implementation is split into:

- Core logic + aiohttp handler: `thomas/nodes/p032_node_command_run.py`
- CLI wiring: `thomas/cli/commands/nodes/p032_node_command_run.py`

## CLI synopsis

```bash
thomas nodes run --node <id|name|ip> <command...>
thomas nodes run --node <id|name|ip> --raw "git status"
thomas nodes run --json --node build-box-01 --raw "uname -a"
```

Supported options (gateway/policy dependent):

- `--node <id|name|ip>`: select the target node.
- `--raw <string>`: run a shell string (`/bin/sh -lc` on POSIX, `cmd.exe /c` on Windows).
- `--cwd <path>`: working directory.
- `--env KEY=VAL` (repeatable): environment overrides.
- `--command-timeout <ms>`: command execution timeout.
- `--invoke-timeout <ms>`: invocation timeout at the gateway layer.
- `--needs-screen-recording`: pass-through requirement flag.
- `--agent <id>`: agent-scoped policies (pass-through).
- `--ask <off|on-miss|always>` / `--security <deny|allowlist|full>`: policy overrides (pass-through).
- `--json`: machine-readable output.

Gateway config:

- `--url` or `THOMAS_URL`
- `--token` or `THOMAS_TOKEN`

## HTTP route

The server handler is exposed at:

- `POST /v1/nodes/run`

Request JSON (`NodeCommandRunRequest`):

```json
{
  "node": "build-box-01",
  "argv": ["/usr/bin/git", "status"],
  "raw": null,
  "cwd": "/repo",
  "env": {"FOO": "bar"},
  "command_timeout_ms": 30000,
  "invoke_timeout_ms": 30000,
  "needs_screen_recording": false,
  "agent": "main",
  "ask": "on-miss",
  "security": "allowlist"
}
```

Response JSON (`NodeCommandRunResponse`):

```json
{
  "ok": true,
  "result": {
    "node": "build-box-01",
    "argv": ["/usr/bin/git", "status"],
    "exit_code": 0,
    "stdout": "...",
    "stderr": "",
    "duration_ms": 42
  }
}
```

Failures return `ok: false` with a deterministic `error.code`:

```json
{
  "ok": false,
  "error": {
    "code": "INVALID_INPUT",
    "message": "Missing command: provide argv (positional args) or raw.",
    "details": null
  }
}
```

## Error codes

- `INVALID_INPUT`: malformed request (missing command, bad timeouts, invalid env, etc.)
- `MISSING_CONFIG`: CLI could not resolve gateway URL/token
- `NODE_UNAVAILABLE`: gateway has no node manager integration
- `COMMAND_TIMEOUT`: execution exceeded the configured timeout
- `INVOKE_FAILED`: network/subprocess/other external failure

## Notes on execution

By default, the server backend **does not** silently execute commands locally if no node manager is available. Instead it returns `NODE_UNAVAILABLE`. (A local subprocess backend exists for unit tests and can be enabled explicitly by callers if needed.)

## Testing

New tests live in:

- `tests/prompt_pack/test_p032_node_command_run.py`

They cover:

- request validation
- local execution backend behavior
- deterministic error reporting
