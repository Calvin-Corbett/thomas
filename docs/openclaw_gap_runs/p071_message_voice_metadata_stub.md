# P071 — Message voice metadata stub

This adds a **Thomas-native** stub for generating voice metadata associated with a message.

## What it does

- Validates input deterministically.
- Produces a stable, machine-readable schema.
- If `audio_path` is provided:
  - records size + SHA-256
  - best-effort inspects WAV files via stdlib `wave` for sample rate / channels / duration
- If `audio_url` is provided:
  - **does not fetch**
  - records URL only
  - requires an explicit config/policy gate (e.g. `voice_metadata_allow_urls: true`)

## CLI

Human output:

```bash
thomas message voice-metadata-stub --message-id msg-123 --audio-path ./note.wav
```

JSON output:

```bash
thomas message voice-metadata-stub --message-id msg-123 --audio-path ./note.wav --json
```

## Result schema (shape)

```json
{
  "ok": true,
  "result": {
    "schema_version": 1,
    "message_id": "msg-123",
    "source": {"kind": "file", "path": "..."},
    "metadata": {
      "duration_ms": 1000,
      "size_bytes": 16044,
      "sha256": "...",
      "mime_type": "audio/x-wav",
      "sample_rate_hz": 8000,
      "channels": 1,
      "bit_depth": 16,
      "codec": "pcm",
      "container": "wav"
    },
    "is_stub": true,
    "warnings": []
  }
}
```

Errors:

```json
{
  "ok": false,
  "error": {
    "code": "invalid_request | missing_config | external_failure",
    "message": "…",
    "details": { "…" : "…" }
  }
}
```

## Tests

```bash
python -m pytest -q tests/prompt_pack/test_p071_message_voice_metadata_stub.py
python -m pytest -q tests/test_cli_parity_commands.py -k "message"
```

## Risks / integration notes

- Command discovery in your repo may expect a specific registration hook; this module exposes `build_parser`, `configure_parser`, `register`, `add_parser`, `run`, and `main` to match common patterns.
- URL policy flag name may differ in your config surface; the implementation checks `voice_metadata_allow_urls`, then falls back to `allow_urls` / `allow_network`.
