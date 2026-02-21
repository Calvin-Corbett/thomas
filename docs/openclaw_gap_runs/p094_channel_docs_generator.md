# P094 — Channel docs generator

This change adds a **channel documentation generator** to the Thomas codebase.

The goal is to make channel setup and automation friendlier by providing a single
source of truth for:

- Which messaging channels are available
- Which configuration knobs they require (env vars / config keys)
- Example CLI invocations
- A machine-readable JSON output mode for tooling (`--json`)

## What was implemented

New modules:

- `thomas/channels/p094_channel_docs_generator.py`
  - Defines the **input contract** (`ChannelDocsRequest`) and **output contract** (`ChannelDocsResult`).
  - Provides deterministic errors via `ChannelDocsGeneratorError` with stable `code` values.
  - Produces:
    - Markdown (`render_markdown`)
    - JSON-serializable structures (`to_machine_readable`)

- `thomas/cli/commands/channel_ops/p094_channel_docs_generator.py`
  - Registers a `docs` subcommand under the existing `channels` CLI group.
  - Supports:
    - `--channel` to filter (comma-separated)
    - `--out` to write to a file
    - `--json` for machine-readable output
    - `--validate-config` to fail fast when required env vars are missing

## CLI usage

```bash
# Generate docs for all discovered channels (Markdown)
thomas channels docs

# Generate docs for Telegram only (Markdown)
thomas channels docs --channel telegram

# Generate machine-readable JSON (includes rendered markdown for convenience)
thomas channels docs --json

# Validate required env vars are set (fails with CONFIG_MISSING)
thomas channels docs --validate-config --json

# Write the output to a file
thomas channels docs --out ./channels.md
```

## JSON output shape

On success (`--json`):

```json
{
  "ok": true,
  "schema_version": 1,
  "generated_at": "2026-02-20T19:43:00+00:00",
  "channels": [
    {
      "name": "telegram",
      "title": "Telegram",
      "summary": "Send and receive messages using the Telegram Bot API.",
      "config": [
        {
          "key": "TELEGRAM_BOT_TOKEN",
          "kind": "env",
          "required": true,
          "description": "...",
          "default": null
        }
      ],
      "examples": ["..."]
    }
  ],
  "markdown": "# Thomas Channels\n..."
}
```

On deterministic failure:

```json
{
  "ok": false,
  "schema_version": 1,
  "error": {
    "code": "UNKNOWN_CHANNEL",
    "message": "Unknown channel name(s).",
    "details": {
      "unknown": ["nope"],
      "known": ["telegram"]
    }
  }
}
```

## Notes

- The generator currently documents the baseline Telegram integration referenced in the prompt context.
- Metadata extraction avoids importing optional third-party libraries at docs-generation time by reading
  module-level constants directly from the integration source file when available.
