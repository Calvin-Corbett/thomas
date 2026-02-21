# P149 — Compat request validation layer

## Goal
Provide a **Thomas-native**, deterministic validation layer for compat-facing payloads (OpenAI-style Chat Completions and Responses create).

This layer is:
- side-effect-free
- machine-readable (stable JSON output)
- conservative (rejects clearly invalid shapes; avoids “best-effort” guessing)

## Server surface

### Route
`POST /gateway/compat/validate`

Body:
```json
{
  "kind": "openai_chat_completions",
  "payload": {
    "model": "gpt-test",
    "messages": [{"role": "user", "content": "hi"}]
  }
}
```

Response (success):
```json
{
  "ok": true,
  "kind": "openai_chat_completions",
  "normalized": {
    "model": "gpt-test",
    "messages": [{"role": "user", "content": "hi"}]
  },
  "errors": []
}
```

Response (failure):
```json
{
  "ok": false,
  "kind": "openai_chat_completions",
  "normalized": {},
  "errors": [
    {"code": "missing_field", "message": "Missing or invalid 'model'.", "path": "$.model"}
  ]
}
```

### Schema
The module exposes a small, stable schema via `json_schema()` for automation tools that want to self-validate request envelopes.

## CLI surface
Entry module: `thomas/cli/commands/gateway/p149_compat_request_validation_layer.py`

Supports:
- JSON string payload
- `@/path/to/payload.json` file payload
- machine-readable output via `--json`
- schema output via `--schema`

Examples:
```bash
python -m thomas.cli.commands.gateway.p149_compat_request_validation_layer --schema
python -m thomas.cli.commands.gateway.p149_compat_request_validation_layer openai_chat_completions '{"model":"gpt-test","messages":[{"role":"user","content":"hi"}]}' --json
```

## Notes
This is a “validation layer” only. It does not perform upstream calls, auth, or routing. It is intended to be used by compat routes and automation as a shared preflight gate.
