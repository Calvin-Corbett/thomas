# P031 - Node command install

## What this adds

Thomas now implements a **`node install`** command that provisions a local “node host” install:

- `node.json` — node host config (gateway connection + node identity)
- `node.env` — environment file containing `THOMAS_GATEWAY_TOKEN`
- `services/thomas-node.service` — a systemd-compatible *user* unit file (written under `THOMAS_HOME` to stay non-invasive)

The behavior is **Thomas-native** (no OpenClaw naming reuse) and designed for deterministic automation.

## CLI

```
thomas node install [--host HOST] [--port PORT] [--tls] [--tls-fingerprint HEX]
                    [--node-id ID] [--display-name NAME] [--runtime python]
                    [--force] [--json]
```

Notes:

- The gateway token is required and must be provided via environment:
  - `THOMAS_GATEWAY_TOKEN` (required)
  - Optional defaults: `THOMAS_GATEWAY_HOST`, `THOMAS_GATEWAY_PORT`
- `--force` is required to overwrite an existing `node.json`.
- `--json` prints machine-readable output with stable keys and error codes.

## Contracts

Core logic contracts live in `thomas.nodes.p031_node_command_install`:

- `NodeInstallRequest` (dataclass input contract)
- `NodeInstallResult` (dataclass output contract)

Failures raise `NodeInstallError` subclasses with stable `.code` values.

For HTTP routing / automation, the module also exposes:

- `NODE_INSTALL_REQUEST_SCHEMA`
- `NODE_INSTALL_RESPONSE_SCHEMA`
- `aiohttp_node_install` (handler)

## Deterministic failure codes

Examples of stable error codes raised:

- `NODE_INSTALL_MISSING_GATEWAY_TOKEN`
- `NODE_INSTALL_ALREADY_INSTALLED`
- `NODE_INSTALL_INVALID_PORT`
- `NODE_INSTALL_INVALID_TLS_FINGERPRINT`
