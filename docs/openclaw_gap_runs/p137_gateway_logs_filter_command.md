# P137 - Gateway logs filter command

This run adds a Thomas-native **gateway logs filter** capability.

## Server API

**POST** `/gateway/logs/filter`

Request body (JSON):

```json
{
  "contains": "ERROR",
  "regex": "timeout",
  "ignore_case": true,
  "levels": ["ERROR", "WARN"],
  "after": "2026-02-20T00:00:00Z",
  "before": "2026-02-21T00:00:00Z",
  "limit": 200,
  "newest_first": false
}
```

Notes:
- If no filters are provided (no `contains`, `regex`, `levels`, `after`, `before`), the route returns the **last N lines** (tail-mode) efficiently.
- `newest_first=true` returns newest matches first and uses a bounded buffer to avoid loading all matches into memory.

Response body (JSON):

```json
{
  "ok": true,
  "matches": [
    {"line_number": 12, "text": "2026-02-20T12:00:01Z ERROR bad thing happened"}
  ],
  "scanned_lines": 842,
  "truncated": false
}
```

Failure response (JSON):

```json
{
  "ok": false,
  "error": {
    "code": "INVALID_INPUT",
    "message": "Invalid request.",
    "fields": {"regex": "invalid regex: ..."}
  }
}
```

## CLI

Human-friendly:

```bash
thomas gateway logs-filter --contains ERROR --limit 50
```

Machine-readable:

```bash
thomas gateway logs-filter --contains ERROR --json
```
