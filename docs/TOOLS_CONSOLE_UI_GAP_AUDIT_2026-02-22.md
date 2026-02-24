# Tools Console + UI Gap Audit (2026-02-22)

Scope: `thomas/server/web/index.html`, `thomas/server/web/js/app.js`, `thomas/server/app.py`, `thomas/server/routes/*`, `docs/FEATURE_CATALOG.md`

## 1) Tools Console Coverage (current)

After this pass, the right-side Tools Console now has:

- `Diagnostics`: runtime snapshot + copy snapshot.
- `System`: `/api/version`, `/api/setup/bootstrap`, `/api/engines`.
- `Models`: `/api/models`, `/api/models/capabilities`, per-profile handshake.
- `Tools`: `/api/tools` registry + categories.
- `Memory`: `/api/memory`, `/api/memory/contradictions`.
- `Runs`: `/api/runs` summary.
- `Events`, `Console`, `Network`: client-side observability.

Primary refs:

- `thomas/server/web/index.html` (tools console tabs + panels)
- `thomas/server/web/js/app.js` (`refreshDebugLiveData`, panel renderers)
- `thomas/server/web/css/components.css` (tab rail + panel styles)

## 2) High-value Thomas features that can be added to Tools Console next

These are implemented server features that are strong Tools Console candidates:

- Mission approval actions (approve/deny):
  - `/api/mission/approvals/autonomy/{approval_id}/decision`
  - `/api/mission/approvals/guardrails/resolve`
  - Ref: `thomas/server/routes/mission.py`

- Mission benchmark controls:
  - `/api/mission/benchmarks/packs`
  - `/api/mission/benchmarks/runs`
  - `/api/mission/benchmarks/run`
  - `/api/mission/benchmarks/jobs`
  - Ref: `thomas/server/routes/mission.py`

- Guardrails approval queue:
  - `/api/approvals/pending`
  - `/api/approvals/resolve`
  - Ref: `thomas/server/guardrails_api.py`

- Webhook operations monitor:
  - `/api/webhooks`, `/api/webhooks/stats/all`, `/api/webhooks/inbox/recent`, retry/test/register/patch/delete
  - Ref: `thomas/server/routes/webhooks_aiohttp.py`

- Replay debugger entry + export quick actions:
  - `/api/runs/{run_id}/events`, `.../replay/*`, `.../export`, `.../export.json`
  - Ref: `thomas/server/routes/runs.py`

- Secrets + local model pull controls:
  - `/api/secrets` (inventory), `/api/secrets/{profile}` (set/clear), `/api/local/pull`
  - Ref: `thomas/server/app.py`, `thomas/server/routes/core_aiohttp.py`

## 3) Features with no current in-app UI interaction path

This section tracks capabilities that currently have no direct interaction path from the main app UI (chat/settings/sidebar/tools).

### A) Route-level gaps (API exists, no in-app control)

- Mission approvals are read-only in UI; no approve/deny buttons.
  - Endpoints exist in `thomas/server/routes/mission.py`
  - UI currently renders approvals only in `thomas/server/web/js/app.js` (`missionRenderApprovals`)

- Mission benchmarks have no UI panel in current main workspace.
  - Endpoints in `thomas/server/routes/mission.py`
  - No calls from `thomas/server/web/js/app.js`

- Guardrails approval endpoints are not wired to UI.
  - `thomas/server/guardrails_api.py`

- Webhook management/inbox endpoints are not wired to UI.
  - `thomas/server/routes/webhooks_aiohttp.py`

- Run replay/export endpoints have no entrypoint in main UI.
  - `thomas/server/routes/runs.py`
  - Standalone replay page exists (`/replay_debugger.html`) but not linked in app shell.

- Audit file endpoints are not exposed in UI.
  - `/api/audit/files`, `/api/audit/runs/{run_id}/files` in `thomas/server/app.py`

- Session fork/import have no UI controls.
  - `/api/session/fork`, `/api/session/import` in `thomas/server/routes/core_aiohttp.py`

- Secret inventory/clear has no direct UI control.
  - `/api/secrets` GET + DELETE `/api/secrets/{profile}` in `thomas/server/routes/core_aiohttp.py`

- Local Ollama pull endpoint has no explicit UI control.
  - `/api/local/pull` in `thomas/server/routes/core_aiohttp.py`

- Codex logout endpoint has no explicit UI control.
  - `/api/codex/logout` in `thomas/server/routes/codex_aiohttp.py`

### B) Implemented surfaces not linked from main shell

- Realtime UI route (`/realtime`) is not linked from sidebar/top-nav.
  - `thomas/realtime/routes.py`

- Autonomy UI route (`/autonomy`) is not linked from sidebar/top-nav.
  - `thomas/autonomy/api.py`

- Companion UI route (`/companion`) exists but page is currently placeholder and unlinked in main shell.
  - `thomas/server/web/companion.html`
  - `thomas/server/routes/companion_aiohttp.py`

### C) Catalog-level feature gaps (major features without dedicated web controls)

From `docs/FEATURE_CATALOG.md`, these major capabilities are mostly chat/CLI/API only and do not have dedicated control panels in the current web shell:

- `integration.telegram`
- `ui.repl_cli`
- `ui.live_browser_smoke`
- `autonomy.media_jobs`
- `memory.fabric_v2` advanced review/curation flows
- `demo.head_to_head_harness`
- `demo.dual_browser_runner`
- `demo.multi_run_campaign`
- `upgrade.doppelganger`

## 4) Suggested next implementation sequence

1. Add approval decision actions in Mission + Tools Console (`approve/deny`, reason input).
2. Add Webhooks tab in Tools Console (list, stats, inbox recent, retry/test).
3. Add Replay tab in Tools Console (recent runs + open replay/export actions).
4. Add Autonomy and Realtime quick-launch links from sidebar.
5. Add Secrets/local-pull controls under Tools Console (advanced mode only).
