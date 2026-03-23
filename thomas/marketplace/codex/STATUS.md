# Module: codex

| Field            | Value                                                  |
|------------------|--------------------------------------------------------|
| Status           | functional (bridge works, hardened in 0.14.34)         |
| Last assessed    | 2026-03-18                                             |
| Assessed by      | claude-opus-4-6 (Cowork session)                       |
| Used in prod     | yes — imported by production code                      |
| Has real tests   | yes (test_codex_provider_tools_policy.py)               |
| Blocking issues  | none currently                                         |

## What This Is

Bridge to OpenAI's Codex app-server. Lets Thomas use a ChatGPT subscription
(via OAuth) instead of requiring a separate API key. 1,127 lines across 4
files. No placeholders — all real code.

## What Actually Works

- `bridge.py` (714 lines) — Spawns `codex app-server` as a subprocess,
  communicates over stdio using JSON-RPC protocol. Handles lifecycle,
  pending request cleanup on stdout close, process liveness guards.
  Hardened in 0.14.34 (dead bridge detection, immediate fail on close).
- `provider.py` (251 lines) — Codex provider with auto-reconnect. Detects
  dead owned bridges and retries one reconnect before surfacing error.
  Hardened in 0.14.34.
- `tools.py` (161 lines) — Tool wrappers for Codex capabilities.

## Known Gaps

- Relies on external `codex` binary being installed
- Windows-focused (subprocess spawning patterns)
- No STATUS.md existed before this one (added 2026-03-18)

## Do Not Touch

- `bridge.py` lifecycle management — carefully hardened. The fail-fast on
  dead subprocess and reconnect logic was specifically fixed after bugs.
