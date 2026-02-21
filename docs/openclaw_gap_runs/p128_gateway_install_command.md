# P128 — Gateway install command

This prompt-pack item adds a **Thomas-native** gateway "install" capability.

## What it does

"Install" means:

- Copy a **local directory** into the configured gateway install directory, **or**
- Extract a **.zip archive** into the configured gateway install directory.

This implementation is intentionally "boring and safe":

- **Zip-slip prevention** (rejects `../` path traversal and absolute paths inside archives)
- **Atomic activation** via a staged temp directory + rename
- Deterministic, machine-readable errors

It does **not** reuse OpenClaw naming or semantics.

## Server API

### POST `/v1/gateway/install`

**Request (JSON):**

```json
{
  "source": "/path/to/plugin_dir_or_archive.zip",
  "name": "optional-install-name",
  "install_dir": "/optional/target/dir",
  "overwrite": false,
  "dry_run": false
}
```

Install directory resolution order when `install_dir` is omitted:

1) Best-effort app config keys (if present)
2) `THOMAS_GATEWAY_INSTALL_DIR` env var

**Response (JSON):**

```json
{
  "ok": true,
  "result": {
    "name": "my_plugin",
    "installed_path": "/target/dir/my_plugin",
    "installed": true,
    "dry_run": false,
    "actions": ["stage /src -> /tmp", "activate /tmp -> /dst"],
    "message": "Installed successfully."
  }
}
```

Errors are deterministic:

```json
{
  "error": {
    "message": "Zip archive contains unsafe path entries.",
    "type": "gateway_install_error",
    "code": "unsafe_archive",
    "details": {"member": "../evil.txt"}
  }
}
```

### GET `/v1/gateway/install/schema`

Returns a compact JSON schema describing request/response contracts.

## CLI

A minimal argparse-based entrypoint is implemented in:

- `thomas/cli/commands/gateway/p128_gateway_install_command.py`

Standalone usage (if invoked directly):

```bash
python -m thomas.cli.commands.gateway.p128_gateway_install_command \
  /path/to/plugin_dir \
  --install-dir /tmp/gateway_plugins \
  --json
```

`--json` emits machine-readable output for automation.
