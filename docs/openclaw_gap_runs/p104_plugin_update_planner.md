# P104 Plugin update planner
This adds a **plugin update planner** to Thomas.

It is a *planner only*: it never installs, updates, or mutates plugins. It answers:

> “Given what’s installed, and what versions exist, what should be updated (and what’s the risk)?”


## What you get

### Tool
- `thomas.plugins.p104_plugin_update_planner.plan_plugin_updates(request)`

### CLI
- `thomas plugins plugin-update-planner ...`
- Alias: `thomas plugins p104-plugin-update-planner ...`

Machine output mode:
- `--json` emits a stable JSON payload (sorted keys + compact formatting).


## Input contract

The request is a JSON object with:

- `installed` (required): either:
  - a list of installed plugins, each either:
    - an object `{ "id": "...", "version": "..." }` (optional `pinned`, `source`), or
    - a shorthand string `"id@version"` (scoped IDs supported, e.g. `"@scope/pkg@1.2.3"`)
  - or an object that contains one of: `installed`, `entries`, or `plugins` as a list

And **one** available-versions source:

- `available`: mapping of plugin id to:
  - a string version `"1.2.3"`, or
  - a list of versions `["1.0.0","1.2.0"]`, or
  - an object like `{ "versions": ["..."] }`
- `catalog_path`: path to a JSON file in the same shapes
- `catalog_url`: URL to a JSON payload in the same shapes (HTTP GET)

Optional:
- `include_prereleases` (bool): default `false`
- `timeout_s` (float): default `10.0` (for `catalog_url`)

The module exports `REQUEST_JSON_SCHEMA` and `RESPONSE_JSON_SCHEMA` for automation.


## Output contract

Success payload:

```json
{
  "ok": true,
  "actions": [
    {
      "id": "alpha",
      "current_version": "1.0.0",
      "latest_version": "1.1.0",
      "status": "update",
      "bump": "minor",
      "risk": "medium",
      "recommended": true,
      "reason": "Update available.",
      "pinned": false,
      "source": null
    }
  ],
  "summary": { "total": 1, "update": 1, "up_to_date": 0, "unknown": 0 }
}
```

`status` meanings:
- `update`: update exists (might be marked `recommended=false` for pinned or major bumps)
- `up_to_date`: installed is already latest
- `unknown`: missing catalog entry, only prereleases exist (and excluded), or a downgrade would be required

Risk is derived from semver bump:
- major → high
- minor → medium
- patch → low


## Deterministic errors

Tool raises (and CLI renders) stable codes:

- `invalid_input`: malformed request, invalid versions, unsupported catalog shape
- `missing_config`: no catalog source / catalog file missing
- `external_failure`: file read failure, HTTP failure, registry registration issues

When running the CLI with `--json`, failures print machine-readable output:

```json
{
  "ok": false,
  "error": {
    "code": "missing_config",
    "message": "Missing available versions. Provide 'available', 'catalog_path', or 'catalog_url'.",
    "details": {}
  }
}
```


## CLI examples

Local files:
```bash
thomas plugins plugin-update-planner \
  --installed ./installed.json \
  --catalog ./catalog.json
```

Machine output:
```bash
thomas plugins plugin-update-planner \
  --installed ./installed.json \
  --catalog ./catalog.json \
  --json
```

URL catalog:
```bash
thomas plugins plugin-update-planner \
  --installed ./installed.json \
  --catalog-url https://example.com/plugin-catalog.json \
  --timeout-s 5 \
  --json
```
