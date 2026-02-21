# P112 - After-response hook

This run adds a **post-response hook** to the Thomas plugin surface area.

In plain terms: after the agent produces a final response, this hook can run to
perform deterministic post-processing (inspection/telemetry) and optional
side-effects.

The reference implementation in this prompt pack is intentionally modest:

- validates input and config with stable error codes
- emits machine-friendly response metadata (counts + sha256)
- optionally writes the response to a file sink

## Contracts

The contracts live in `thomas/plugins/p112_plugin_hook_after_response.py`:

- `AfterResponseHookRequest`
- `AfterResponseHookConfig`
- `AfterResponseHookResult`

### Request schema

```bash
python -m thomas.cli.commands.plugins.p112_plugin_hook_after_response --schema request
```

### Config schema

```bash
python -m thomas.cli.commands.plugins.p112_plugin_hook_after_response --schema config
```

### Response envelope schema

```bash
python -m thomas.cli.commands.plugins.p112_plugin_hook_after_response --schema envelope
```

## CLI usage

### Minimal run

```bash
python -m thomas.cli.commands.plugins.p112_plugin_hook_after_response --response "Hello from Thomas" --json
```

### File sink

```bash
python -m thomas.cli.commands.plugins.p112_plugin_hook_after_response   --response "Write me"   --sink file   --file-path /tmp/thomas_after_response.log   --json
```

## Error behavior

Errors are deterministic and machine-readable:

- `missing_config` - config was not provided to the hook
- `invalid_config` - config was provided but invalid
- `invalid_input` - request was malformed
- `external_failure` - a side-effect failed (e.g., file write)

In `--json` mode, failures exit non-zero and return:

```json
{"ok": false, "error": {"code": "…", "message": "…", "details": {}}}
```
