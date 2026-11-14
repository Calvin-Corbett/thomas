### Fixed

- Build stream recovery and stop confirmation treat HTTP 404 `run_not_found` naming the requested run as no active run, so pruned or restart-lost slots no longer keep the task locked or fail stop confirmation. Stop confirmation rejects missing-run answers naming another run. Active and recording runs still wait; other status failures are not treated as completion.

- `GET /api/evolve/agent/status` now returns HTTP 404 with `ok=false`, `code=run_not_found`, and the requested run ID when an explicit nonblank `run_id` resolves to neither a selected registered slot nor a recovered run. Default idle status and conversation-only polling before the first run remain HTTP 200; existing selection, recording, and persistence behavior is unchanged.
