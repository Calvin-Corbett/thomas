# P075 - Channel provider interface contract

## Overview

Adds a Thomas-native contract for messaging channel providers.

- Stable request/response schemas
- Deterministic error codes
- Minimal adaptor for common provider shapes

Implementation:

- `thomas/channels/p075_channel_provider_interface_contract.py`
- `thomas/cli/commands/channel_ops/p075_channel_provider_interface_contract.py`

## Actions

- `describe` – provider metadata (capabilities, config keys)
- `health_check` – optional lightweight check
- `send` – send a message

## Error codes

- `invalid_input`
- `missing_config`
- `provider_not_found`
- `provider_load_failed`
- `provider_external_failure`

## CLI

```bash
thomas channels provider-contract telegram --action describe --json
```
