# Feature 11 — OpenAPI → Tool Auto-Generator (Thomas) — v4

This is a *meaningful* upgrade aimed at what people actually want when they “import an API”:

## Consumer-loved wins (why v4 is better)
### 1) **Freeze Spec Snapshot**
Real APIs change, links break, and auth-protected specs go offline.
`api.import` now supports:
- `freeze_spec: true` → stores a compressed snapshot of the spec in `thomas_imported_apis.json`.
- On restart, `ApiImporter.reload_saved()` prefers the frozen snapshot (no network dependency).

### 2) **Trust + Debuggability (per-tool extras)**
Every generated tool accepts:
- `__dry_run: true` → returns the *constructed HTTP request* (headers redacted) without sending it.
- `__trace: true` → includes redacted request metadata in `ToolResult.meta`.
- `__auth` → per-call auth override (token or `Header: value`).
- `__base_url` → per-call base url override.
- `__timeout_seconds` → per-call timeout override.

This is the “I don’t trust black boxes” feature. People love this.

### 3) Better Query Encoding
- OpenAPI 3: practical support for `explode`, `style=form`, `style=deepObject`
- Swagger2: supports `collectionFormat` (csv/ssv/tsv/pipes/multi)

### 4) Body UX Improvements
- JSON requests accept either `body` (whole object) **or** inline fields.
- If `body` is a dict, inline keys are merged in (without clobbering).
- Request body `required: true` now actually matters.

## Files
- `thomas/core/api_importer.py`
- `thomas/tools/api_import.py`
- `tests/test_api_importer_v4.py`

## Tool naming
`api.{api_name}.{operationId_or_fallback}` with collision-safe suffixes.

## Auth
- `auth_header` may be:
  - token: `sk_live_...` (bearer scheme adds `Bearer`)
  - exact header line: `X-API-Key: ...`
  - basic: `user:pass` (auto-encoded) or `Basic ...`

Secrets are NOT stored. For restart-safe tokens:
`THOMAS_API_AUTH_{NAME_UPPER}`

## Startup wiring
```python
from thomas.tools.api_import import build_api_import_tools

for t in build_api_import_tools(registry):
    registry.register(t)

from thomas.core.api_importer import ApiImporter
ApiImporter().reload_saved(registry)
```

## Example: dry run
```json
{
  "__dry_run": true,
  "__trace": true
}
```
returns the request without sending it (redacts auth headers).

## File uploads (multipart)
For `format: binary` or Swagger2 `type: file`, pass:
- `"C:\\path\\to\\file.png"`
- `{"path":"C:\\path\\to\\file.png","filename":"file.png","content_type":"image/png"}`
- `("C:\\path\\to\\file.png","image/png")`
- `("C:\\path\\to\\file.png","file.png","image/png")`

## Limits
- External `$ref` doc max: 2MB (change in `_ExternalRefFetcher`).
- Spec snapshot max: ~4MB in storage (compressed+base64). Large specs will skip snapshot.
