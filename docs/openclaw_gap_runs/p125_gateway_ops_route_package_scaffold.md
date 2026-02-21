# P125 Gateway ops route package scaffold

This adds a small scaffolder for creating a new **gateway ops route package** inside a Thomas checkout.

The goal is to speed up adding new “ops” endpoints by generating a predictable, importable package under:

`thomas/server/routes/gateway/ops/<package_name>/`

## What gets created

Given:

- `project_root`: path to the Thomas project root (must contain a `thomas/` directory)
- `package_name`: valid Python identifier (letters/digits/underscore; not a keyword)

The scaffolder will:

1. Ensure the directories exist:
   - `thomas/server/routes/gateway/ops/`
   - `thomas/server/routes/gateway/ops/<package_name>/`
2. Create minimal `__init__.py` files for:
   - `gateway/ops/` (if missing)
   - `gateway/ops/<package_name>/` (if missing)
   - any intermediate directories that were created by this operation
3. Create a starter `routes.py` in the leaf package (never overwrites existing files).

The operation is **idempotent**: running it multiple times will not modify existing files.

## CLI usage

### Basic

```bash
python -m thomas.cli gateway-ops-route-package-scaffold --project-root /path/to/Thomas fleet_ops
```

### Machine-readable output

```bash
python -m thomas.cli gateway-ops-route-package-scaffold --project-root /path/to/Thomas --json fleet_ops
```

### Schema

```bash
python -m thomas.cli gateway-ops-route-package-scaffold --schema
```

### Project root discovery

If `--project-root` is omitted, the command uses:

- `THOMAS_PROJECT_ROOT`

If neither is available, the command fails with a deterministic `missing_config` error.

## HTTP route

When running the Thomas server, this module defines:

- `GET  /gateway/ops/route-package-scaffold/schema`
- `POST /gateway/ops/route-package-scaffold`

Whether these are active depends on how your server wires route modules. The module exports a `routes` `RouteTableDef` and a `register(app)` helper.

### Request JSON

```json
{
  "package_name": "fleet_ops",
  "project_root": "/path/to/Thomas",
  "dry_run": false
}
```

### Success response JSON

```json
{
  "ok": true,
  "result": {
    "project_root": "/path/to/Thomas",
    "package_name": "fleet_ops",
    "package_dir": "/path/to/Thomas/thomas/server/routes/gateway/ops/fleet_ops",
    "created_dirs": [],
    "created_files": [],
    "skipped": []
  }
}
```

### Error response JSON

```json
{
  "ok": false,
  "error": {
    "code": "invalid_input",
    "message": "package_name must be a valid Python identifier (letters, digits, underscores)",
    "details": {
      "field": "package_name",
      "value": "bad-name"
    }
  }
}
```

## Error codes

The scaffolder returns deterministic error payloads using these codes:

- `invalid_input` — request fields are missing or malformed
- `missing_config` — the project root cannot be resolved or does not look like a Thomas checkout
- `external_failure` — filesystem conflict or OS-level failure
