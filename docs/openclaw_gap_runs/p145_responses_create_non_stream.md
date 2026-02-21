# P145 — Responses create (non-stream)

## Summary

Adds **non-streaming** support for creating a response using an OpenAI-style *Responses API* request shape.

This implementation is **Thomas-native** (no OpenClaw naming reuse). It includes:

- Clear request and response contracts
- Deterministic, machine-readable errors
- Unit tests for success + failure modes
- Automation-friendly CLI output via `--json`

## Server

### Route

- **Method**: `POST`
- **Path**: `/v1/responses`

### Request (contract)

Minimal required JSON:

```json
{
  "model": "<model id>",
  "input": "<text input>",
  "stream": false
}
```

Compatibility notes:

- `stream: true` is rejected with a deterministic 400 error (this prompt covers non-stream only).
- The handler accepts `messages` in place of `input` for client compatibility.
- `max_tokens` is accepted as an alias for `max_output_tokens`.

### Response (contract)

On success, returns a minimal OpenAI-like response object:

```json
{
  "id": "resp_...",
  "object": "response",
  "created_at": 123,
  "status": "completed",
  "model": "...",
  "output": [
    {
      "type": "message",
      "role": "assistant",
      "content": [{"type": "output_text", "text": "..."}]
    }
  ],
  "usage": {
    "input_tokens": 0,
    "output_tokens": 0,
    "total_tokens": 0
  }
}
```

### Errors

Errors are deterministic and machine-readable:

```json
{
  "error": {
    "message": "...",
    "type": "invalid_request_error",
    "code": "...",
    "param": "..."
  }
}
```

## CLI

A CLI command is provided for automation:

```bash
thomas p145-responses-create-non-stream --model test-model --input "hello" --json
```

Defaults:

- Base URL: `THOMAS_BASE_URL` or `http://127.0.0.1:8080`
- Timeout: 60 seconds (configurable via `--timeout-s`)

## Tests

- `tests/prompt_pack/test_p145_responses_create_non_stream.py`
