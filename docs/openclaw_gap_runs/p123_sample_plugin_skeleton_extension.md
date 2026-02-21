# P123 — Sample plugin skeleton extension

This prompt-pack item adds a **small, deterministic example plugin** to the Thomas
codebase.

It is intentionally boring (in the good way): the goal is to show how to wire a
plugin end-to-end with:

- a clear request/response contract (JSON Schema)
- deterministic error shapes
- a CLI wrapper that supports `--json`

## What the plugin does

It renders a message as:

```
<prefix>: <message> [repeated N times]
```

By default, the prefix is `Thomas`. If `use_config=true`, the prefix is read from a
small JSON config file.

### Optional config

If config mode is enabled, the plugin loads JSON from either:

- CLI: `--config-path <path>`
- Environment: `THOMAS_P123_SAMPLE_PLUGIN_CONFIG=<path>`

Config file format:

```json
{ "prefix": "Custom" }
```

## CLI usage

Human output:

```bash
thomas plugins p123-sample-plugin-skeleton-extension "hello" --times 2 --uppercase
# Thomas: HELLO HELLO
```

Machine output:

```bash
thomas plugins p123-sample-plugin-skeleton-extension "hello" --times 2 --uppercase --json
# {"ok":true,"plugin_id":"...","result":{...}}
```

Schema output:

```bash
thomas plugins p123-sample-plugin-skeleton-extension --schema
```

## Gateway/API payloads

The plugin module exposes request/response JSON Schemas via `manifest()`.

### Request example

```json
{
  "message": "hello",
  "times": 2,
  "uppercase": true,
  "use_config": false
}
```

### Success wrapper

```json
{
  "ok": true,
  "plugin_id": "p123_sample_plugin_skeleton_extension",
  "result": {
    "rendered": "Thomas: HELLO HELLO",
    "prefix": "Thomas",
    "used_config": false
  }
}
```

### Error wrapper

```json
{
  "ok": false,
  "plugin_id": "p123_sample_plugin_skeleton_extension",
  "error": {
    "code": "missing_config",
    "message": "Config path not provided",
    "details": {
      "expected_env": "THOMAS_P123_SAMPLE_PLUGIN_CONFIG"
    },
    "retryable": false
  }
}
```
