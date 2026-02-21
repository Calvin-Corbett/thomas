# Integration Report — Thomas Autonomy Engine (Patch Files Only)

This zip contains **changed files only** (mostly new files) that add a production-grade background Autonomy Engine to Thomas.
It is designed as a **plugin-style integration** so you only need a **small, boring** wiring change in your aiohttp app
factory to enable it.

## What you get

- **SQLite job queue** (`AutonomyStore`): migration-safe schema versioning, WAL mode, robust row-locking for single-process concurrency.
- **Scheduler**: `once`, `interval`, `daily`, `weekly` schedule types.
- **Retry policy**: exponential backoff + jitter, transient error classification.
- **Dead-letter**: jobs that exhaust retry attempts become `dead` with captured traceback.
- **Approvals**: policy-driven approvals (risk classes low/medium/high/critical).
- **Audit trail**: persisted audit events for job lifecycle, approvals, engine start/stop, errors.
- **UI**: `web/autonomy.html` + JS/CSS, plus `/autonomy` route redirect.
- **API**: `/api/autonomy/*` endpoints to manage jobs, approvals, audit, messages, briefings.
- **Daily briefing**: built-in recurring job created once on startup (08:00 America/Chicago by default).

## Files added

- `thomas/autonomy/*` (engine, store, policy, scheduler, adapters, API, plugin, docs)
- `web/autonomy.html`, `web/autonomy.js`, `web/autonomy.css`
- `tests/test_autonomy_store.py`, `tests/test_autonomy_engine.py`, `tests/test_autonomy_api.py`
- `INTEGRATION_REPORT.md` (this file)

## One-line server integration

In your aiohttp server/app factory (where you already register `/api/chat`), add:

```python
from thomas.autonomy import install_autonomy

# after app + config exist
if getattr(config, "autonomy", None) and getattr(config.autonomy, "enabled", False):
    install_autonomy(
        app,
        config,
        api_token=getattr(config.autonomy, "api_token", None),
    )
```

If you don't have a `config.autonomy` object yet, the fastest option is environment flags:

```python
enabled = os.getenv("THOMAS_AUTONOMY_ENABLED", "0") == "1"
token = os.getenv("THOMAS_AUTONOMY_TOKEN")  # optional

if enabled:
    install_autonomy(app, config, api_token=token)
```

The plugin will place these keys on the aiohttp app:

- `app["autonomy_engine"]`
- `app["autonomy_store"]`
- `app["autonomy_policy"]`

## Database + policy file locations

**DB default** (if your config exposes a memory root path):
- `<config.memory.root_path>/autonomy/autonomy.sqlite3`

Fallback:
- `runtime/.thomas/autonomy/autonomy.sqlite3`

**Policy file default** (next to the DB):
- `autonomy_policy.toml`

Example `autonomy_policy.toml`:

```toml
[risk.low]
mode = "allow"

[risk.medium]
mode = "approve"

[risk.high]
mode = "deny"

[risk.critical]
mode = "deny"

[kinds.reminder]
risk_class = "low"
mode = "allow"

[api]
require_token = true
```

## UI

After enabling the plugin, open:

- `http://<thomas-host>/autonomy`  (redirects to `/autonomy.html`)

If you set an API token, enter it in the UI and it will be stored in localStorage.

## Guardrails / Human approvals

- Risk class determines whether a job runs automatically, requires approval, or is denied.
- Approvals are created automatically for `medium` risk jobs under the default policy.
- Approve/deny from the UI or via the API.

## “Integrate with existing chat sessions and memory”

This patch includes **adapters** with *optional* integration points:

- If your app injects `app["chat_submit_json"]` (async callable), Autonomy can call chat internally.
- If your app injects `app["memory_append"]` / `app["memory_query"]`, Autonomy will write/read structured memory events.

This avoids hard-coding assumptions about your existing memory + session internals, while still providing a clean way
to wire everything up.

## Tests

Run:

```bash
pytest -q
```

The tests cover:
- migrations + store CRUD
- approvals flow
- engine execution for low/medium risk reminder jobs
- API create/list endpoints via aiohttp test server

## Next upgrade steps (recommended)

1. **Bind Autonomy to your Guardrails system**:
   - Map job kinds / action categories to risk classes.
   - Require approvals for filesystem/network/process actions by default.

2. **Tie briefings into your Memory “nightly compiler”**:
   - Briefings can reference the prior day’s memory delta and open tasks.

3. **Promote autonomy_task from demo to deep autonomy**:
   - Expand the planner schema to include tool-call-like structured actions.
   - Add richer reviewer heuristics (e.g., file writes, network, process control).
   - Feed the job queue state + pinned goals into planning context.

This patch already includes a built-in `autonomy_task` job kind implementing planner → reviewer → executor,
so the remaining work is mostly about making the plan schema and reviewer stricter over time.


## Static file hosting note

The Autonomy UI is served directly from Python package resources (stdlib `importlib.resources`), so it will work
even if your Thomas server does **not** currently expose the `web/` directory. The files are also included under
`web/` for convenience, but the runtime source of truth is `thomas/autonomy/ui/*`.
