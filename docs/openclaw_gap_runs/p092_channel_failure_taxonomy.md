# P092 — Channel failure taxonomy

This run adds a **channel failure taxonomy** to Thomas: a small, stable set of failure categories that can be used to classify outbound messaging failures across providers (Telegram, etc.) without scraping provider-specific strings.

## What it does

`thomas channels failure-taxonomy` can:

- **List** the canonical failure categories (human-readable by default).
- **Classify** a structured failure event (JSON) into one category.
- Emit **machine-readable JSON** via `--json` for automation.
- Emit a **JSON schema** for the machine-readable output via `--schema`.

The taxonomy is provider-agnostic first, with optional provider-specific guidance layered on top when `--channel` is specified.

## CLI usage

### List taxonomy

```bash
thomas channels failure-taxonomy
thomas channels failure-taxonomy --json
```

### Classify a failure event

```bash
thomas channels failure-taxonomy \
  --channel telegram \
  --event '{"http_status":429,"message":"Too Many Requests: retry after 7"}' \
  --json
```

You can also pass the event via file:

```bash
thomas channels failure-taxonomy --event-file ./failure.json --json
```

### Validate config (offline-safe)

Probe performs offline validation only (no network calls). For Telegram it validates presence and basic shape of a bot token.

```bash
thomas channels failure-taxonomy \
  --channel telegram \
  --probe \
  --config '{"token":"123456:ABCDEF..."}' \
  --json
```

### Emit JSON schema

```bash
thomas channels failure-taxonomy --schema
```

## JSON output

With `--json`, the command prints either:

- a success object shaped like `FailureTaxonomyReport.to_dict()`, or
- an error object shaped like `ChannelFailureTaxonomyError.to_dict()`.

The schema for both is available via `--schema`.

## Deterministic error handling

Errors are deterministic and machine-friendly in `--json` mode:

- `invalid_input` (exit code `2`)
- `missing_config` (exit code `3`)
- `external_failure` (exit code `4`)
