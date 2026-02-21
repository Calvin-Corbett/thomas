# P131 - Gateway discover command

## What this adds

Thomas now supports discovering **running Thomas Gateway instances on the local network** using **mDNS/DNS-SD** (Bonjour-style discovery).

The feature is exposed in two places:

1) **Server route** (machine-readable JSON):

- `GET /gateway/discover`

2) **CLI command** (human output by default, machine output with `--json`):

- `thomas gateway discover`

## Server API

### Request

`GET /gateway/discover`

Query parameters:

- `timeout_ms` (or `timeout`): integer, milliseconds (default: `2000`)
- `domain`: DNS-SD suffix, must end with `.` (default: `local.`)
- `service_type` (or `service`): DNS-SD service type (default: `_thomas-gw._tcp`)
- `schema`: if truthy, return a schema document instead of performing discovery

### Response

Success:

```json
{
  "ok": true,
  "result": {
    "service_type": "_thomas-gw._tcp",
    "domain": "local.",
    "timeout_ms": 2000,
    "elapsed_ms": 14,
    "beacons": [
      {
        "instance_name": "Thomas Gateway._thomas-gw._tcp.local",
        "host": "gw.local",
        "port": 18789,
        "addresses": ["192.168.1.10"],
        "ws_url": "ws://gw.local:18789",
        "txt": {"role": "gateway"}
      }
    ]
  }
}
```

Schema mode:

```bash
GET /gateway/discover?schema=1
```

Failure:

```json
{
  "ok": false,
  "error": {
    "code": "invalid_input",
    "message": "timeout_ms must be an integer",
    "details": {"timeout_ms": "not_an_int"}
  }
}
```

## CLI

Human output:

```bash
thomas gateway discover
```

Machine output:

```bash
thomas gateway discover --json
```

Schema output:

```bash
thomas gateway discover --schema
```

Optional flags:

- `--timeout-ms 4000`
- `--domain local.`
- `--service-type _thomas-gw._tcp`
