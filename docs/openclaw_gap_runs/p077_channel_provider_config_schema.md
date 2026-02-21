# P077 — Channel provider config schema

## What shipped

Thomas can now **emit a JSON Schema** for a given channel provider’s configuration.

This supports:
- pre-flight validation (before runtime)
- auto-generated setup UIs / forms
- automation tooling (`--json` output)

## Provider resolution

Provider modules are resolved using the Thomas convention:

- `thomas.integrations.<provider>`

Provider names are accepted as `a-zA-Z0-9_-` and normalized for imports as:
- lowercase
- `-` becomes `_`

## Schema discovery order

1. Explicit schema dict constant:
   - `PROVIDER_CONFIG_JSON_SCHEMA`
   - `PROVIDER_CONFIG_SCHEMA`
   - `CHANNEL_PROVIDER_CONFIG_SCHEMA`
   - `CONFIG_JSON_SCHEMA`
   - `CONFIG_SCHEMA`

2. Explicit function returning a dict:
   - `get_config_schema()`
   - `config_schema()`
   - `get_provider_config_schema()`

3. Inferred from a config model type:
   - `dataclass`
   - `TypedDict`
   - `pydantic.BaseModel` (v1 or v2)
   - annotated class with `__annotations__`

## CLI

```bash
thomas channels provider-config-schema <provider>
thomas channels provider-config-schema <provider> --json
```

### Example (machine-readable)

```json
{
  "ok": true,
  "provider": "telegram",
  "source_module": "thomas.integrations.telegram",
  "schema": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "title": "TelegramConfig",
    "properties": {
      "token": { "type": "string" }
    },
    "required": ["token"],
    "additionalProperties": false
  }
}
```

### Errors (machine-readable)

```json
{
  "ok": false,
  "error": {
    "code": "PROVIDER_NOT_FOUND",
    "message": "Channel provider module not found",
    "provider": "telegram",
    "details": { "attempted_modules": ["thomas.integrations.telegram"] }
  }
}
```
