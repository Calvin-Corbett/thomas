# P095 - Channel provider contract tests

This gap run adds a **provider contract test runner** for Thomas channels.

The goal: before you try to ship a real message, verify that a provider integration is:

1) Importable
2) Configured
3) (Optionally) able to reach its upstream API using a safe, read-only check

The implementation is deliberately automation-friendly:

- Deterministic error codes for failures
- `--json` mode for machine parsing
- `--schema` mode for tooling that wants a JSON schema

## CLI

The command is registered under the `channels` group:

```bash
thomas channels provider-contract-tests --help
```

### Telegram example

Run basic checks (no outbound network call):

```bash
thomas channels provider-contract-tests --provider telegram --token "123:ABC" --chat-id "456"
```

Run checks + a read-only external health check (Telegram `getMe`):

```bash
thomas channels provider-contract-tests \
  --provider telegram \
  --token "123:ABC" \
  --chat-id "456" \
  --external
```

Machine-readable mode:

```bash
thomas channels provider-contract-tests --provider telegram --json
```

Schema output:

```bash
thomas channels provider-contract-tests --schema
```

## Programmatic API

Use the runner directly:

```python
from thomas.channels.p095_channel_provider_contract_tests import (
    ProviderContractTestRequest,
    run_channel_provider_contract_tests,
)

report = run_channel_provider_contract_tests(
    ProviderContractTestRequest(
        provider="telegram",
        config={"token": "123:ABC", "chat_id": "456"},
        run_external=True,
    )
)

assert report.ok
```

## Error codes

The runner emits stable error codes in `errors[*].code`:

- `invalid_request`
- `provider_not_found`
- `provider_import_failed`
- `missing_config`
- `external_failure`
