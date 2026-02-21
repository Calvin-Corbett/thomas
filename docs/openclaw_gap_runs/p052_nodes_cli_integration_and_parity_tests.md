# P052 — Nodes CLI integration and parity tests

This change adds a Thomas-native **nodes/devices** CLI surface and a small parity validator
for the server's nodes endpoint.

## What shipped

- A `nodes` CLI group (also available as `devices`) with:
  - `list` — fetch node/device inventory from the Thomas server
  - `parity` — minimal endpoint parity checks (reachability + supported JSON schema)
- Machine-readable output via `--json`
- Deterministic error codes for automation

## CLI examples

Human output:

```bash
python -m thomas.cli.main nodes list --base-url http://127.0.0.1:8080
```

JSON output:

```bash
python -m thomas.cli.main nodes list --base-url http://127.0.0.1:8080 --json
python -m thomas.cli.main nodes parity --base-url http://127.0.0.1:8080 --json
```

## Error contract

Errors are raised as `NodesCliIntegrationError` and surfaced in JSON form as:

```json
{
  "ok": false,
  "error": {
    "code": "missing_config",
    "message": "…",
    "details": {}
  }
}
```

Common error codes:

- `missing_config` — base URL is not provided and not found in environment
- `invalid_input` — invalid base URL/path/timeout
- `external_failure` — server unreachable or returned an error status
- `invalid_response` — server returned JSON that cannot be normalized to nodes
