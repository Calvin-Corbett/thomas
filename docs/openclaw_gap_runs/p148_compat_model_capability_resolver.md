# P148 — Compat model capability resolver

Implements a small “capability resolver” intended to support compatibility layers (for example, OpenAI-style routes) by answering:

- “Given a model id string, what features should the compat layer assume are supported?”

This is deliberately conservative. If a capability can’t be inferred, it defaults to `false`, and deployments can override behavior deterministically via configuration.

## Resolver (pure function)

`resolve_compat_model_capabilities({"model": "..."}) -> {"ok": true|false, ...}`

Capabilities currently reported:

- `supports_chat_completions`
- `supports_responses_api`
- `supports_streaming`
- `supports_function_tools`
- `supports_json_schema_response_format`
- `family` (coarse hint only)
- `notes` (non-normative hints)

## Server route (gateway)

Best-effort AIOHTTP handler is included for auto-discovery registrars:

- `GET  /gateway/compat/model-capabilities?model=...`
- `POST /gateway/compat/model-capabilities` with JSON body `{"model": "..."}`

Route hooks provided (so the gateway loader can choose what it prefers):

- `register_routes(router)`
- `get_routes() -> list[(method, path, handler)]`

## CLI (local/offline)

```bash
thomas gateway compat-model-capabilities --model gpt-4.1-mini --json
```

## Overrides / configuration

Environment variable: `THOMAS_COMPAT_MODEL_CAPS_JSON`

- can be a JSON object string
- or a path to a JSON file containing an object

Example:

```json
{
  "gpt-4.1-mini": {
    "supports_json_schema_response_format": true
  },
  "my-backend-prefix:*": {
    "supports_responses_api": false,
    "supports_streaming": false
  }
}
```

If the config cannot be parsed/loaded, the resolver returns a deterministic error:

```json
{"ok": false, "error": {"code": "invalid_config", "message": "..."}}
```
