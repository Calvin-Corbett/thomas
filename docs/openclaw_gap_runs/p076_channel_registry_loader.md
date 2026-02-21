# P076 - Channel registry loader

This gap run adds a **channel registry loader** to Thomas. The goal is to give both the runtime and the CLI a *single*, validated way to discover configured messaging channels (Telegram, webhooks, etc.) from a registry file.

## What it does

- Loads a channel registry file in **YAML**, **JSON**, or **TOML**.
- Normalizes registry entries into a stable in-memory structure.
- Supports `${ENV_VAR}` and `${ENV_VAR:-default}` value substitution.
- Provides deterministic, machine-readable error codes.
- Exposes a CLI command (under `channels`) that can emit `--json` output, plus a `--json-schema` helper for automation.

## Registry format

Supported shapes:

### List form

```yaml
channels:
  - name: alerts
    kind: telegram
    config:
      token: ${BOT_TOKEN}
      chat_id: ${CHAT_ID}
```

### Shorthand mapping form

```yaml
version: 1
alerts:
  kind: telegram
  token: ${BOT_TOKEN}
  chat_id: ${CHAT_ID}
```

Notes:
- Top-level non-dict keys like `version`/`schema` are treated as metadata and ignored.
- For shorthand entries, any keys other than `name/kind/enabled/config` are treated as provider config.

## CLI

The command is registered as:

- `channels registry-load`

Common usage:

```bash
thomas channels registry-load --path channels.yaml
thomas channels registry-load --path channels.yaml --json
thomas channels registry-load --json-schema
```

## Validation notes

- Strict validation is *best effort*: it validates known channel kinds (currently `telegram`) but preserves unknown channel kinds for forward compatibility.
- Missing env vars in `${VAR}` substitutions are treated as validation errors. Use `${VAR:-default}` to provide safe defaults.
