
# CODEX_README.md — Integrate Time-Travel Debugger into Thomas (F:\DevHub\Thomas)

Goal (Thomas-grade):
- /api/chat records run_id and persists every streamed event
- first NDJSON line is run_start
- UI lists runs, filters/searches, replays into inspector, exports debug pack
- pytest passes

Constraints:
- no new third-party deps
- Windows compatible
- minimal-change but correct

## Steps for Codex

1) Copy new files into repo (same paths):
- thomas/observability/run_store.py
- thomas/server/routes/runs.py
- thomas/server/web/js/runs.js
- thomas/server/web/js/inspector_bridge.js
- tests/test_run_store_retention.py

2) Wire routes during app startup:
- ensure `app["config"] = config`
- `from thomas.server.routes.runs import register_runs_routes`
- `register_runs_routes(app, config)`

3) Instrument /api/chat (critical):
- `run_id = run_store.create_run({...})`
- `writer = run_store.ThreadedRunWriter(run_id)`
- emit & persist first event: run_start
- for each streamed event:
  - persist (writer.record(evt))
  - then write NDJSON to response
- finalize run on done/error
- close writer in finally

4) UI:
- Add sidebar button `navRuns` in index.html
- In sidebar/router, mount runs view:
  - `import { mountRunsView } from "./runs.js";`
  - mount into existing main content container

5) Inspector integration:
Expose a stable hook:
```js
window.ThomasInspector = {
  reset: () => { ... },
  consumeEvent: (evt) => { ...same handler as live stream... },
  setRunId: (runId) => { ...update header label... }
};
```

6) Verify:
- GET /api/runs returns runs
- replay streams NDJSON and populates inspector without model calls
- export downloads zip with 5 files

7) Tests:
`python -m pytest -q`
