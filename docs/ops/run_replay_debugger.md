# Run Replay Debugger (Operator Guide)

Feature: `observability.run_replay_debugger`

This feature is for post-mortem debugging of chat/autonomy runs by replaying the run event stream (HTTP context, prompts, tool calls/outputs, model chunks, and any state patches your runtime emits) with deterministic ordering.

## Typical workflow: debug a failed run

1) Find the run_id
- Check the server logs for the `X-Thomas-Run-Id` header (this middleware adds it on tracked endpoints), or
- If your UI shows run ids, copy the id.

2) Open the replay debugger UI
- `/replay_debugger.html?run_id=<RUN_ID>`

3) Scrub + filter
- Use the slider to jump by event index.
- Use step -1 / +1 to walk event-by-event.
- Filter by event type and use search.

4) Stream replay (NDJSON)
- `/api/runs/<RUN_ID>/replay_stream?from=0&speed=1`
- `speed=0` disables delays.

5) Share replay artifact (redacted)
- `/api/runs/<RUN_ID>/export.json`
- This payload is redacted: keys/tokens/passwords/etc become `[REDACTED]`.

## Redaction behavior

Redaction is applied at API read/export time:
- Keys like `authorization`, `api_key`, `token`, `password`, etc are replaced with `[REDACTED]`.
- Common secret patterns (Bearer tokens, JWTs, sk-… keys, etc) are scrubbed inside strings too.
- Optional extra regexes:
  - `THOMAS_REDACTION_REGEXES='["my_regex_here"]'`

Optional write-time redaction (off by default):
- `THOMAS_REDACT_AT_WRITE=1`

## Persistence model

This feature pack provides an internal SQLite schema (created if missing) at:
- `~/.thomas/runs.sqlite3` by default
- Override with: `THOMAS_RUNS_DB_PATH=/path/to/runs.sqlite3`

Tables:
- `runs(run_id, started_at, ended_at, ok, error, meta_json, last_seq)`
- `events(run_id, t_ms, seq, event_type, payload_json)`

Deterministic ordering:
- replay reads order by `(seq, id)`.

## Integration notes

This pack installs:
- an aiohttp middleware that starts/attaches a run context for `/api/chat`, `/api/autonomy`, `/api/agent` requests
- a best-effort auto-instrumentation layer that wraps likely tool/model entrypoints (non-breaking)

If your repo already has strong event logging, the recorder will prefer your existing `thomas.observability.run_store` event writer when detected.
