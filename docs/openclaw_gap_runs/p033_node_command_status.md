# P033 – Node command status

This gap run adds a **node command status** capability to Thomas.

## What it does

Given a `command_id`, Thomas can return the latest known status for that command:

- `queued` / `running` / `succeeded` / `failed` / `unknown`
- `done` and `success` flags (when known)
- optional `exit_code`, `stdout`, `stderr`, and a freeform `message`

This is intentionally shaped as a small, stable API so it can be used from:

- the CLI (`thomas nodes command-status ...`)
- server routes (JSON schema provided)

## CLI usage

Human-readable output:

```bash
thomas nodes command-status <command_id>
```

Some CLI entrypoints also expose the nested form:

```bash
thomas nodes command status <command_id>
```

Machine-readable JSON output (prints the response object on stdout):

```bash
thomas nodes command-status <command_id> --json
```

Include stdout/stderr when available:

```bash
thomas nodes command-status <command_id> --include-output --json
```

### CLI error JSON

On failure with `--json`, the CLI prints a machine-readable error object to stdout and exits non-zero:

```json
{"code": "...", "message": "...", "detail": "..."}
```

## Configuration

The implementation supports a conservative, deterministic on-disk state backend.

Configuration discovery order:

1. An explicit `state_dir` passed via the internal request object (used by tests).
2. `THOMAS_NODE_COMMAND_STATE_DIR` – directory containing `<command_id>.json`.
3. `THOMAS_STATE_DIR` – uses `<THOMAS_STATE_DIR>/node_commands`.
4. `THOMAS_CONFIG` – path to a JSON config file supporting:
   - `node_command_state_dir` (absolute directory)
   - `state_dir` (uses `<state_dir>/node_commands`)
5. `~/.thomas/config.json` – supports the same keys as `THOMAS_CONFIG`.

If none are available, the command fails with a deterministic **missing_config** error.

## Machine-readable contracts

### Request

`NodeCommandStatusRequest` (dataclass):

- `command_id: str` (required)
- `node_id: Optional[str]`
- `include_output: bool`
- `state_dir: Optional[pathlib.Path]` (override)

### Response

`NodeCommandStatusResponse` (dataclass):

- `command_id: str`
- `node_id: Optional[str]`
- `state: str`
- `done: bool`
- `success: Optional[bool]`
- `exit_code: Optional[int]`
- `stdout: Optional[str]`
- `stderr: Optional[str]`
- `message: Optional[str]`
- `retrieved_at_epoch_s: int`

JSON schema is available via `node_command_status_response_schema()`.

## Error behavior

Errors are deterministic and machine-readable:

- `invalid_input` (exit code 2)
- `missing_config` (exit code 3)
- `not_found` (exit code 4)
- `external_failure` (exit code 5)

If calling via HTTP, the module exposes optional aiohttp routes:

- `GET /nodes/commands/{command_id}/status`
- `GET /nodes/commands/status/schema`

These routes are only active if the Thomas server registers this module’s `routes`.
