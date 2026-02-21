# P016 - Browser data cookies export and import

## Summary

This gap run adds a Thomas-native way to **export** and **import** cookies for a
browser profile.

- CLI route: `thomas browser data cookies export|import`
- Supports **machine-readable output** via `--json`.
- Supports **JSON** and **ZIP** cookie bundles:
  - JSON: a single `cookies.json` file
  - ZIP: a `.zip` archive containing a `cookies.json` member

## CLI usage

### Export

Export cookies from a profile:

```bash
thomas browser data cookies export ./cookies.json --profile-dir /path/to/profile
```

Export cookies to ZIP (recommended for portability):

```bash
thomas browser data cookies export ./cookies.zip --profile-dir /path/to/profile
# (or explicitly)
thomas browser data cookies export ./cookies.any --profile-dir /path/to/profile --format zip
```

### Import

Import cookies into a profile:

```bash
thomas browser data cookies import ./cookies.json --profile-dir /path/to/profile
```

Import cookies from ZIP:

```bash
thomas browser data cookies import ./cookies.zip --profile-dir /path/to/profile
# (or explicitly)
thomas browser data cookies import ./cookies.any --profile-dir /path/to/profile --format zip
```

Machine-readable output:

```bash
thomas browser data cookies export ./cookies.zip --profile-dir /path/to/profile --json
```

## Cookies file format

The exporter writes a JSON object:

```json
{
  "schema": "thomas.browser.cookies.v1",
  "exported_at": "2026-02-20T00:00:00+00:00",
  "cookies": [
    {"name": "...", "value": "...", "domain": "...", "path": "/"}
  ]
}
```

When exporting to ZIP, the archive contains **exactly that JSON** as `cookies.json`.

The importer also accepts:

- a raw cookie list (`[...]`)
- a Playwright `storage_state`-style object (must contain `cookies: [...]`)

## Error handling

Errors are deterministic and categorized:

- `INVALID_INPUT` – unreadable file, invalid JSON/zip, invalid cookie shape
- `MISSING_CONFIG` – no profile directory provided (and env var not set)
- `EXTERNAL_FAILURE` – Playwright launch failures, filesystem write errors, etc.
