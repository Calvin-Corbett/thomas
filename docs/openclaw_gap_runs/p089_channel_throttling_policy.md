# P089 - Channel throttling policy

## What this adds

Thomas now has a **token-bucket** throttling policy that can be used to rate-limit outbound channel traffic (example: messaging integrations).

It supports:

- **Bursts** up to `burst`
- A steady-state refill rate `rate_per_second`
- A deterministic **retry-after** value when blocked
- Optional state persistence in a JSON file (best-effort cross-process lock)
- **Machine-readable output** via `--json`

## CLI usage

This module provides a CLI op called:

- `throttling-policy`

### Evaluate a decision (human output)

```bash
thomas channels throttling-policy --channel telegram --burst 5 --rate-per-second 1.0
```

### Evaluate a decision (JSON)

```bash
thomas channels throttling-policy \
  --channel telegram \
  --bucket-key telegram:chat:123 \
  --burst 2 \
  --rate-per-second 1 \
  --state-file .thomas_throttle_state.json \
  --json
```

Example output:

```json
{
  "ok": true,
  "decision": {
    "schema_version": 1,
    "allowed": true,
    "retry_after_seconds": 0.0,
    "bucket_key": "telegram:chat:123",
    "now": 1700000000.0,
    "cost": 1.0,
    "config": {"rate_per_second": 1.0, "burst": 2},
    "state": {"tokens": 1.0, "updated_at": 1700000000.0}
  }
}
```

### Load policy config from a JSON file

```json
{
  "defaults": {"rate_per_second": 0.5, "burst": 2},
  "channels": {
    "telegram": {"messages_per_minute": 20, "burst": 10}
  }
}
```

```bash
thomas channels throttling-policy --channel telegram --config ./throttle_policy.json --json
```

## Library usage

```python
from thomas.channels.p089_channel_throttling_policy import (
    ChannelThrottlePolicy,
    ThrottlePolicyConfig,
    ThrottleCheckRequest,
)

policy = ChannelThrottlePolicy(ThrottlePolicyConfig(rate_per_second=1.0, burst=5))
decision = policy.evaluate(ThrottleCheckRequest(bucket_key="telegram:chat:123"))

if not decision.allowed:
    print("Wait", decision.retry_after_seconds)
```
