# P142 — OpenAI tool-call passthrough mapping

This prompt pack adds a **gateway-native** normalization step for **OpenAI Chat Completions** tool calls so transcripts remain replayable across providers.

Some OpenAI-compatible providers emit tool-call IDs that include characters (or leading/trailing whitespace) that are accepted by OpenAI but rejected by stricter providers (common strict pattern: `^[A-Za-z0-9_-]+$`). If Thomas stores those IDs in a transcript and later replays the session through a stricter provider, the run can fail purely due to invalid identifiers.

## What this implements

A deterministic remapper that:

- Reads OpenAI `assistant` messages containing `tool_calls[]`.
- Sanitizes each `tool_calls[].id` into a strict, provider-neutral identifier set.
- Applies the same mapping to `tool` messages’ `tool_call_id`.
- Returns updated messages plus the mapping table for correlation/automation.

Collision handling is deterministic (stable hash suffix + numeric fallback).

## Server route

Two route aliases are registered (same behavior):

- `POST /v1/gateway/p142_openai_tool_call_passthrough_mapping`
- `POST /gateway/p142_openai_tool_call_passthrough_mapping`

Schema endpoint (two aliases):

- `GET /v1/gateway/p142_openai_tool_call_passthrough_mapping/schema`
- `GET /gateway/p142_openai_tool_call_passthrough_mapping/schema`

### Request

Preferred request shape:

```json
{
  "messages": [
    {
      "role": "assistant",
      "tool_calls": [
        {
          "id": "functions.read:0",
          "type": "function",
          "function": {"name": "read", "arguments": "{}"}
        }
      ]
    },
    {"role": "tool", "tool_call_id": "functions.read:0", "content": "ok"}
  ],
  "policy": "strict"
}
```

Convenience shape: the request body can also be the `messages` array directly.

### Response

Success:

```json
{
  "ok": true,
  "result": {
    "messages": [...],
    "tool_call_id_map": {"functions.read:0": "functions_read_0", "...": "..."},
    "changed": true,
    "stats": {
      "total_tool_calls": 1,
      "remapped_tool_calls": 1,
      "total_tool_results": 1,
      "remapped_tool_results": 1
    }
  }
}
```

Failure:

```json
{
  "ok": false,
  "error": {"code": "unknown_tool_call_id", "message": "...", "details": {...}}
}
```

## CLI

A parity CLI entry is provided for automation-friendly runs:

```bash
thomas gateway p142-openai-tool-call-passthrough-mapping \
  --server-url http://localhost:8000 \
  --input payload.json \
  --json
```

Schema:

```bash
thomas gateway p142-openai-tool-call-passthrough-mapping \
  --server-url http://localhost:8000 \
  --schema
```

- If `--input` is omitted, the command uses a small built-in sample payload.
- If `--input -` is used, JSON is read from stdin.
- If `THOMAS_SERVER_URL` is set, `--server-url` can be omitted.
