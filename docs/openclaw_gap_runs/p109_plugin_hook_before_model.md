# P109 - Plugin hook before-model

## What this adds

Thomas now has a **before-model** plugin hook: a synchronous step that can
inspect and mutate a model request right before it is executed.

This gap-run implementation is **Thomas-native**:
- naming is Thomas-oriented (no OpenClaw naming reuse)
- contracts are explicit (dataclasses + TypedDict)
- failures are deterministic and machine-readable

## Where it lives

- Runtime hook: `thomas/plugins/p109_plugin_hook_before_model.py`
- CLI parity command: `thomas/cli/commands/plugins/p109_plugin_hook_before_model.py`

## Contracts

### Input (request)

A JSON object with at minimum:

```json
{
  "messages": [
    {"role": "user", "content": "hi"}
  ],
  "model": "optional-model-id",
  "metadata": {"any": "mapping"}
}
```

### Config

```json
{
  "inject_system": "system prompt to inject",
  "max_inject_chars": 4096,
  "simulate_external_failure": false
}
```

### Output

Success payload:

```json
{
  "ok": true,
  "result": {
    "applied": true,
    "messages": [
      {"role": "system", "content": "..."},
      {"role": "user", "content": "hi"}
    ],
    "model": null,
    "metadata": {
      "before_model": {"injected": true, "inject_chars": 3}
    }
  }
}
```

Failure payload (stable error codes):

```json
{
  "ok": false,
  "error": {
    "code": "MISSING_CONFIG",
    "message": "Missing required config: 'inject_system'.",
    "details": {"required": ["inject_system"]}
  }
}
```

Codes:
- `INVALID_INPUT`
- `INVALID_CONFIG`
- `MISSING_CONFIG`
- `EXTERNAL_FAILURE`

## CLI usage

### Run (human output)

```bash
python -m thomas plugins p109-before-model run \
  --request '{"messages":[{"role":"user","content":"hi"}]}' \
  --config '{"inject_system":"You are helpful."}'
```

### Run (machine-readable JSON)

```bash
python -m thomas plugins p109-before-model run \
  --request '{"messages":[{"role":"user","content":"hi"}]}' \
  --config '{"inject_system":"SYS"}' \
  --json
```

### Pipe input / read from file

`--request` and `--config` also support `@file.json` and `@-` (stdin):

```bash
cat request.json | python -m thomas plugins p109-before-model run --config @config.json --json
```

### Schema

```bash
python -m thomas plugins p109-before-model schema --json
```
