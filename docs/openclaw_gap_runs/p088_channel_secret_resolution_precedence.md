# P088 — Channel secret resolution precedence (Thomas)

This gap run adds a single, consistent rule-set for how Thomas chooses a channel secret when multiple sources are available.

## Precedence order

When resolving a secret value, Thomas now checks sources in this exact order (highest → lowest):

1. **CLI override** (`cli_spec`)
2. **Channel configuration** (`channel_spec`)
3. **Environment variables** (`env_var_names`, or provider defaults when not supplied)
4. **Global / integration configuration** (`config_spec`)

If a higher-precedence source is explicitly provided but cannot be resolved (for example, an env var is referenced but not set, or a file cannot be read), resolution **fails deterministically** with a structured error.

## Secret spec formats

A secret can be provided as a **spec string** in any of these forms:

- `literal-value` (default): treated as the secret itself
- `env:NAME` or `${NAME}`: read the value from environment variable `NAME`
- `file:/path/to/secret.txt`: read UTF-8 file contents and `strip()` whitespace

## Machine-readable output

The CLI op added under `thomas channels` supports JSON output via `--json`.

- Success emits a JSON object that includes:
  - `provider`, `secret_key`, `source`, `spec_type`
  - `secret` **redacted** (stable redaction; last 4 chars preserved when present)
- Failure emits a JSON object:
  - `ok: false`
  - `error.code`, `error.message`, and `error.details`

## Deterministic errors

The resolver raises only these error types:

- `InvalidSecretRequestError` (`invalid_secret_request`)
- `SecretNotFoundError` (`secret_not_found`)
- `SecretSourceError` (`secret_source_error`)
