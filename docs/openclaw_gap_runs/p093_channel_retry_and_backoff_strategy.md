# P093 - Channel retry and backoff strategy

## What this adds

Thomas now has a **channel-agnostic retry/backoff strategy** that can be used by
integrations (e.g. Telegram) and surfaced via the `thomas channels` CLI.

The implementation lives in:

- `thomas/channels/p093_channel_retry_and_backoff_strategy.py` (core primitives)
- `thomas/cli/commands/channel_ops/p093_channel_retry_and_backoff_strategy.py` (CLI op)

## Design goals

- **Deterministic behavior**: given the same inputs, the backoff plan is stable.
- **Strict validation**: invalid configuration raises typed, predictable errors.
- **No channel coupling**: the strategy does not import Telegram/Slack/etc.
- **Automation-friendly**: CLI supports `--json` output and JSON schema.
- **Deterministic failure modes**: CLI emits stable error codes and exits with well-defined status.

## RetryPolicy

`RetryPolicy` is a dataclass with validation:

- `max_attempts` (>= 1): total attempts including the initial call
- `base_delay_s` (>= 0): delay before the first retry
- `max_delay_s` (> 0): clamp for any computed delay
- `backoff_factor` (>= 1): exponential multiplier
- `jitter` (0..1): optional ± fraction jitter
- `jitter_seed`: required when `jitter > 0` to keep results deterministic
- `retry_on_status_codes`: HTTP-like status codes treated as transient (defaults include 429 and common 5xx)

## Classification heuristics

When executing with retries, exceptions are classified conservatively into:

- `rate_limit` (e.g. exception has `retry_after` attribute)
- `server` (exception has integer `status_code` in `retry_on_status_codes`)
- `network` (built-in `TimeoutError`, `ConnectionError`, `OSError`, plus common HTTP client exception bases when installed)
- `unknown` (not retryable)

## CLI

A new `channels` operation is registered:

```bash
thomas channels retry-backoff --attempts 5 --base-delay 0.5 --factor 2 --max-delay 30
thomas channels retry-backoff --json
thomas channels retry-backoff --schema
```

`--config` can be used to point at a JSON policy file; explicit CLI options
override file values.

## Machine readable output

Success (`--json`):

```json
{ "ok": true, "plan": { "policy": {"...": "..."}, "steps": [], "total_delay_s": 0.0 } }
```

Failure (`--json`):

```json
{ "ok": false, "error": { "code": "config_not_found", "message": "..." } }
```

Exit codes:

- `0`: success
- `2`: deterministic, typed retry/backoff configuration errors
- `1`: unexpected/untyped failure

`--schema` prints the JSON schema describing the `--json` payload.

## Testing

The prompt-pack test suite validates:

- exponential backoff calculation + max-delay clamping
- deterministic jitter enforcement
- success/failure behavior of `call_with_retry_or_raise`
- argparse registration + `--json` output
- deterministic JSON error output for missing config files
