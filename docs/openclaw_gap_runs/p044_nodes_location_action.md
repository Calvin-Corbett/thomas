# P044 — Nodes location action

This gap-run adds a **Thomas-native** node action for fetching device location, designed to be usable from both CLI and HTTP layers.

## What it does

The action invokes the node command:

- `location.get`

and expects a payload containing latitude/longitude (plus optional metadata like accuracy and timestamp).

### Output fields (result)

- `lat`, `lon` (required)
- `accuracy_meters` (optional)
- `altitude_meters` (optional)
- `speed_mps` (optional)
- `heading_deg` (optional)
- `timestamp` (required; ISO-8601 preferred, epoch seconds/ms also accepted)
- `is_precise` (optional)
- `source` (optional)

## CLI

A `nodes location get` command is added with a machine-readable mode:

```bash
thomas nodes location get --node <id|name|ip> --accuracy precise --max-age 15000 --location-timeout 10000 --json
```

In JSON mode the CLI prints a stable envelope:

- Success: `{ "ok": true, "result": { ... } }`
- Failure: `{ "ok": false, "error": { "code": "...", "message": "...", "details": { ... } } }`

## Errors

Errors are deterministic and include a stable `code`:

- `invalid_input` — bad CLI/route input (missing node id, bad timeouts, invalid accuracy)
- `missing_config` — no configured node invoker/client
- `external_failure` — gateway/node invocation failed
- `invalid_response` — the node returned an unexpected shape

If the node returns its own structured error (`{ ok: false, error: {...} }`), Thomas passes through the upstream `code` and `message`.
