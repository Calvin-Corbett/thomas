# P130 – Gateway probe command

Adds a **Gateway probe** capability to Thomas.

Implemented as:
- **Server route**: `POST /probe` (typically mounted under a gateway prefix, e.g. `/gateway/probe`)
- **CLI**: `thomas gateway probe`

The probe checks whether the configured gateway target is reachable via HTTP.

## CLI usage

Probe configured target:

```bash
thomas gateway probe
```

Target resolution order:
1. `--target`
2. `THOMAS_GATEWAY_URL` (fallbacks: `THOMAS_GATEWAY_TARGET`, `THOMAS_GATEWAY`)
3. Thomas config (best-effort; implementation-defined)

Probe explicit target:

```bash
thomas gateway probe --target http://127.0.0.1:18789
```

Machine-readable output:

```bash
thomas gateway probe --json
```

## Server route

Request JSON (all fields optional):

```json
{
  "target": "http://127.0.0.1:18789",
  "timeout_s": 3.0,
  "path": "/"
}
```

Response JSON:

- `ok` (bool)
- `target` (str)
- `latency_ms` (int | null)
- `status_code` (int | null)
- `error` ({`code`, `message`} | null)

Status codes:
- `200` on success
- `502` on probe failure (timeout/unreachable/bad_status)
- `400` on invalid input / missing config
