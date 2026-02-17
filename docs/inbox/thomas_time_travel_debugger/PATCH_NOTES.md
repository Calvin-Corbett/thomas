
# PATCH_NOTES.md — Time-Travel Debugger (Thomas-grade patch pack)

This zip is a **Thomas-grade patch pack**: new files + concrete diffs + Codex instructions.
I can’t directly edit your existing `app.py` / UI files from here, so the pack includes:

- Drop-in new modules you add as-is
- Unified diffs under `patches/` showing intended minimal edits for existing files
- `CODEX_README.md`: a Codex task list to fully integrate + verify in your repo

---

## Server: sqlite run store
New: `thomas/observability/run_store.py`

Upgrades vs v1:
- Adds `events.search_text` + extraction for search/filter.
- Optional `events_fts` (FTS5) for fast text search if sqlite build supports it.
- Adds `ThreadedRunWriter` for batched inserts during /api/chat streaming.

Retention:
- Keep last `MAX_RUNS` (default 500).
- Best-effort size cap `MAX_DB_BYTES` (~200MB): deletes oldest runs in batches.

Note: sqlite files don’t always shrink after deletes without VACUUM. Deletes still prevent unbounded growth.

---

## Server: routes
New: `thomas/server/routes/runs.py`

Endpoints:
- `GET /api/runs`
- `GET /api/runs/{run_id}`
- `GET /api/runs/{run_id}/replay` (NDJSON)
- `GET /api/runs/{run_id}/export` (debug pack zip)

Export pack:
- `run.json`
- `events.ndjson`
- `conversation.json` (best-effort reconstruction)
- `config_summary.json` (whitelist-first to avoid secrets)
- `README.txt` (repro steps)

---

## Web UI
New:
- `thomas/server/web/js/runs.js`
- `thomas/server/web/js/inspector_bridge.js`

Wire a sidebar item to mount runs view, and expose a stable inspector consumer:
- `window.ThomasInspector.consumeEvent(evt)`
- `window.ThomasInspector.reset()`
- `window.ThomasInspector.setRunId(runId)`

---

## Tests
New: `tests/test_run_store_retention.py`

Run:
`python -m pytest -q`
