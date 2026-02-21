# P012 - Browser artifact accessibility snapshot

This feature adds an artifact capture mode that writes a **machine-readable accessibility snapshot**
(AX tree-style JSON) to the configured artifact directory.

## What it does

- Pulls an accessibility snapshot from the current live browser session.
- Writes it to `*.json` as an artifact.
- Emits a small JSON envelope suitable for automation.

## CLI usage

```bash
thomas browser artifact-accessibility-snapshot \
  --artifact-dir ./artifacts \
  --name homepage_ax \
  --json
```

### Output schema (`--json`)

Success:

```json
{
  "ok": true,
  "artifact_path": ".../homepage_ax.json",
  "snapshot": { "role": "WebArea", "name": "…", "children": [] }
}
```

Failure:

```json
{
  "ok": false,
  "error": {
    "code": "missing_config|invalid_input|external_failure",
    "message": "...",
    "details": { "optional": true }
  }
}
```

## Environment configuration

If `--artifact-dir` is not provided, the command will look for:

- `THOMAS_ARTIFACT_DIR`

If neither is set, the command fails deterministically with `missing_config`.

## Deterministic exit codes

- `invalid_input` -> 2
- `missing_config` -> 3
- `external_failure` -> 4
