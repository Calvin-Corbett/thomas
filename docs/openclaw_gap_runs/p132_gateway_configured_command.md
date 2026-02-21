# P132 - Gateway configured command

## What this adds

This prompt adds a small "configured" probe for the Thomas Gateway:

- **Server route**: returns a machine-readable JSON object describing whether the Gateway is configured.
- **CLI command**: prints human output by default and supports `--json` for automation.

This is designed to support onboarding flows and scripting.

## Server API

The route is registered under two paths to be resilient to different router prefixing strategies:

- `GET /configured`
- `GET /gateway/configured`

Response shape (stable keys):

```json
{
  "configured": true,
  "gateway_mode": "local",
  "config_path": "~/.thomas/thomas.json",
  "missing": [],
  "reason": null,
  "message": "Gateway is configured.",
  "source": "app"
}
```

Reason codes when `configured=false`:

- `missing_config` — no readable config found (app did not load one and disk fallback missing)
- `invalid_config` — config exists but could not be parsed as JSON in disk fallback
- `missing_gateway_mode` — config exists, but gateway mode could not be determined
- `unexpected_error` — last-resort fallback

## CLI usage

Offline check (reads configuration locally):

```bash
thomas gateway configured
thomas gateway configured --json
```

Probe a running Gateway over HTTP:

```bash
thomas gateway configured --url http://127.0.0.1:8000
thomas gateway configured --url http://127.0.0.1:8000 --json
```

Exit codes:

- `0` = configured
- `2` = not configured
- `3` = could not determine (invalid input or network failure)
