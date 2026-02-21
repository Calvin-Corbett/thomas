# P146 – Responses create stream events

This run adds **Responses API streaming events** support to the Thomas gateway.

The goal is to support the OpenAI-style **semantic SSE** event stream emitted by `POST /v1/responses` when `stream: true` is provided.

## HTTP API

### Create a response (streaming)

**Request**

`POST /v1/responses`

```json
{
  "model": "gpt-5",
  "input": "Say 'double bubble bath' ten times fast.",
  "stream": true
}
```

**Response**

`Content-Type: text/event-stream`

A sequence of Server-Sent Events (SSE), each made of:

- `event: <event-type>`
- `data: <json>`
- blank line

Common event types include:

- `response.created`
- `response.output_text.delta`
- `response.completed`

### Machine-readable stream (JSON wrapper)

For automation (or for environments that don’t like SSE), Thomas supports:

`POST /v1/responses?format=json`

with the same request body. Instead of SSE, it returns:

```json
{ "events": [ /* event objects */ ] }
```

### JSON schema for automation

`GET /v1/responses/streaming-events/schema`

Returns:

- `request_schema`
- `event_schema`

## CLI

```bash
thomas gateway p146-responses-create-stream-events --input "hello" --json
```

Behavior:

- default: prints SSE text to stdout
- `--json`: prints a JSON array of event objects
- `--base-url`: calls a running server at `<base-url>` using `?format=json`

## Configuration

By default, Thomas runs in **stub** mode (no external calls).

To enable proxy mode (forward to an upstream `/v1/responses`):

```bash
export THOMAS_GATEWAY_RESPONSES_MODE=proxy
export THOMAS_GATEWAY_RESPONSES_UPSTREAM_URL="http://localhost:8080"
export THOMAS_GATEWAY_RESPONSES_API_KEY="..."   # optional
```

In proxy mode, Thomas forwards the upstream response to the client.
