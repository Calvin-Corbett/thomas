# P140 — OpenAI Chat Completions (non-stream)

This prompt-pack entry adds **non-stream** support for the OpenAI-compatible `POST /v1/chat/completions` endpoint in the Thomas gateway server.

## What it does

- Accepts an OpenAI Chat Completions request (must be `stream=false` / omitted).
- Forwards it to an OpenAI-compatible upstream (`/v1/chat/completions`).
- Returns upstream JSON as-is (success and JSON error responses).
- Wraps non-JSON upstream failures in a deterministic OpenAI-shaped error payload.
- Provides a machine-readable JSON Schema endpoint for automation.

## Configuration

Set these environment variables for the Thomas server (and the CLI command, if used):

- `OPENAI_API_KEY` — required
- `OPENAI_BASE_URL` — optional (defaults to `https://api.openai.com/v1`)
  - You may set this to a mock server base URL in tests, e.g. `http://127.0.0.1:8001`

Optional:

- `OPENAI_TIMEOUT_S` — request timeout in seconds (default: `30`)

## Server usage

Example request:

```bash
curl -sS \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"hello"}]}' \
  http://localhost:8080/v1/chat/completions
```

Schema endpoint:

```bash
curl -sS http://localhost:8080/gateway/p140/openai/chat-completions-non-stream/schema | jq
```

## CLI usage

The CLI module provides an argparse-style entrypoint and discovery hooks. In environments where Thomas registers gateway commands automatically, the command name is:

- `p140-openai-chat-completions-non-stream`

Machine-readable output:

```bash
thomas gateway p140-openai-chat-completions-non-stream --json \
  --model gpt-4o-mini --user "hello"
```
