# P141 — OpenAI chat completions stream (Thomas)

This prompt-pack run adds a Thomas **gateway endpoint** that proxies the
OpenAI **Chat Completions** streaming API (SSE).

Even though OpenAI exposes `/v1/chat/completions`, this is *not* an OpenClaw
compatibility shim; it is a Thomas-native gateway route with deterministic
errors and a CLI harness for parity testing.

## Server route

The route module is:

- `thomas/server/routes/gateway/p141_openai_chat_completions_stream.py`

It registers multiple aliases (to tolerate small routing differences across
Thomas deployments):

- `POST /gateway/p141/openai_chat_completions_stream`
- `POST /gateway/p141/openai-chat-completions-stream`
- `POST /gateway/openai/chat_completions/stream`
- `POST /gateway/openai/chat-completions/stream`
- `POST /gateway/openai/chat/completions/stream`

If your Thomas server mounts APIs under `/api`, the same paths should also be
available under `/api/...`.

### Required configuration

The route requires an OpenAI API key:

- `OPENAI_API_KEY` — required
- `OPENAI_BASE_URL` — optional (defaults to `https://api.openai.com/v1`)
- `OPENAI_TIMEOUT_S` — optional (defaults to `60`)

Config can also be provided through `app["config"]` if your Thomas server uses
an application config mapping.

### Request contract

Minimal required JSON:

```json
{
  "model": "gpt-4o-mini",
  "messages": [{"role": "user", "content": "Hello"}],
  "stream": true
}
```

All additional keys are forwarded to the upstream OpenAI API.

### Response

- When `stream=true` (default), the route **streams SSE** in OpenAI's standard
  format, including the terminal `data: [DONE]`.
- When `stream=false`, the route returns a **single JSON response** (passthrough
  from upstream) and is suitable for automation.

Errors are returned as JSON:

```json
{
  "ok": false,
  "error": {
    "code": "invalid_request",
    "message": "..."
  }
}
```

## CLI command

The CLI harness is:

- `thomas/cli/commands/gateway/p141_openai_chat_completions_stream.py`

It exposes a command name:

- `p141-openai-chat-completions-stream`

Example:

```bash
thomas p141-openai-chat-completions-stream \
  --server http://127.0.0.1:8000 \
  --model gpt-4o-mini \
  --message "Say hello"
```

Machine-readable mode:

```bash
thomas p141-openai-chat-completions-stream \
  --server http://127.0.0.1:8000 \
  --model gpt-4o-mini \
  --message "Say hello" \
  --json
```

Outputs:

```json
{"ok": true, "model": "gpt-4o-mini", "text": "Hello ..."}
```

## Tests

- `tests/prompt_pack/test_p141_openai_chat_completions_stream.py`

The tests spin up a stub OpenAI-compatible upstream server and verify:

- Streaming passthrough works and includes `data: [DONE]`
- Deterministic errors for invalid input and missing config
- Upstream errors map to a stable gateway error
