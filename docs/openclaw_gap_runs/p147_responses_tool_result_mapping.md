# P147 - Responses tool result mapping

## What this adds

This adds a **Thomas-native** mapping utility that converts an internal tool execution result into a **Responses-style “tool output” envelope**.

This is meant to be reused by your gateway “Responses create” flows once tool calls execute, and it can also be exercised via an optional HTTP endpoint + CLI.

No OpenClaw naming is reused.

## Core API

Module:

- `thomas.server.routes.gateway.p147_responses_tool_result_mapping`

Function:

- `map_tool_result_to_responses_tool_output(req: ToolResultMapRequest) -> ToolResultMapResponse`

Behavior:

- Requires `tool_call_id`
- If `is_error=True`, requires `error_code` and `error_message`
- If `is_error=False`, requires `result`
- Deterministic validation errors are raised as `DeterministicMappingError(code, message)`

Output shape (compat-friendly):

- Always includes:
  - `content`: structured list of `output_json` or `output_text`
  - `output`: convenience field holding the same value in a simple form
- Error outputs include:
  - `status: "failed"`
  - `error: {code, message}`

## Optional HTTP endpoint

If your gateway’s route aggregation mounts `get_aiohttp_routes()`, it exposes:

- `POST /gateway/responses/tool-result-map`

Body: `ToolResultMapRequest`

## CLI command

Command module:

- `thomas/cli/commands/gateway/p147_responses_tool_result_mapping.py`

## Tests

Owned tests:

- `tests/prompt_pack/test_p147_responses_tool_result_mapping.py`
