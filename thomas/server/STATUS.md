# Module: server

| Field            | Value                                                    |
|------------------|----------------------------------------------------------|
| Status           | functional (actively developed, some scaffold subsystems)|
| Last assessed    | 2026-03-18                                               |
| Assessed by      | claude-opus-4-6 (Cowork session) + Calvin (product owner)|
| Used in prod     | yes — this IS the production runtime                     |
| Has real tests   | partial (route tests exist, coverage varies widely)      |
| Blocking issues  | 2 files over hard size limit, gateway is scaffold        |

## What This Is

The aiohttp web server that runs Thomas. Serves the web UI, the chat API,
companion (mobile PWA), mission control, plugin marketplace, local project
launcher, webhooks, observability endpoints, and an OpenAI-compatible gateway.
This is 39,000+ lines across 113 Python files plus a full HTML/JS/CSS frontend.

## Product Vision (from Calvin, 2026-03-18)

Thomas is **the everything assistant.** Key identity points:

- **User-nameable.** Thomas is the product, not the name. The user can call
  their assistant Thomas, Susan, Bobby, whatever they want. The name belongs
  to the user.
- **Robot mascots are constitutional.** The little pixel-robot characters are
  core to the identity of Thomas. They're not decoration — they're the brand.
  Every UI surface, every interaction, should feel like your robot is there.
- **Memory is the superpower.** Thomas is supposed to have really, really good
  memory. Detailed, persistent, cross-session. This is the #1 thing that should
  differentiate Thomas from other assistants. **It does not work yet** as of
  this assessment. This is the most important gap.
- **"Everything" means everything.** The broad scope is intentional. Don't
  narrow it. The goal is one assistant that handles whatever you throw at it.

## Honest Assessment

### What works (production-used):
- **Web UI boot** (`app.py` → `app_part01-04.py`): aiohttp server starts,
  routes register, middleware loads. This works.
- **Chat routes** (`chat_aiohttp*.py`, `chat_helpers.py`, `chat_stream_events.py`):
  The core AI conversation loop works. Streaming, tool use, agent mode.
- **Web frontend** (`web/index.html`, `app_runtime_primary.mjs`): Chat UI,
  sidebar, nav, settings, marketplace surface — all functional.
- **Desktop plugins** (`desktop_plugins.py` facade → `_manifest.py` + `_runtime.py`):
  Install, enable/disable, uninstall flow works. Split was done in 0.14.36
  to satisfy size gate.
- **Plugin marketplace** (`marketplace_catalog_aiohttp.py`, `plugin_hosting.py`):
  Functional — browse, install from store, manual ZIP import.
- **Companion** (`companion_aiohttp.py`, `companion_runtime.py`): Mobile PWA
  surface exists and serves.
- **Local projects** (`local_projects_aiohttp.py`): Link folders, launch apps.
  Works but the file is 1252 lines — **over the 800 limit**.
- **Observability** (`observability.py`): Live agent presence data as of 0.14.37.
- **Life manager** (`life_manager_aiohttp.py`): Tasks, agenda, habits, goals.
  Installable plugin with CRUD state.

### What's scaffold / incomplete:
- **Gateway** (`routes/gateway/`): 25+ numbered stub files (`p125_` through
  `p150_`). OpenAI-compatible and Responses API compat routes. These are
  scaffold — the file naming convention (p125, p126...) suggests they were
  auto-generated or batch-created. Need to assess which are real vs empty.
- **Mission system** (`mission*.py` — 10 route files): Spread across
  `mission.py`, `mission_approvals.py`, `mission_autonomy_runtime.py`,
  `mission_content_hub.py`,
  `mission_content_hub_constants.py`, `mission_control_routes.py`,
  `mission_cron.py`, `mission_runtime_views.py`, `mission_support.py`,
  `mission_tasks.py`, `mission_workflows.py`. This is fragmented —
  unclear which parts are functional vs aspirational.
- **Swarm mode** (`swarm_mode.py`): Just a compatibility shim. The real
  code moved to `thomas/agent/swarm`. This file exists only so old test
  patches don't break. 27 lines.
- **Webhooks** (`webhooks.py`, `webhooks_aiohttp.py`, `webhooks_delivery.py`,
  `webhooks_utils.py`): 4 files, largest is 1183 lines. Needs assessment
  of what's wired vs what's scaffold.

### Architecture violations (pre-existing as of 2026-03-18):
- `routes/chat_aiohttp_part02.py`: **1212 lines** (hard ceiling is 1200). MUST split.
- `routes/local_projects_aiohttp.py`: **1252 lines** (limit 800). MUST split.

## Known Gaps

- Memory does not work yet — this is the biggest product gap
- Gateway stubs need audit (which are real vs empty scaffold?)
- Mission system is scattered across 10+ files — unclear boundaries
- 2 files failing architecture size gate
- No STATUS.md existed before this one (added 2026-03-18)
- Web frontend dead code in `web/js/app_parts/` — agents told not to touch,
  but it's still there taking up space
- Companion app needs assessment — unclear how complete the mobile experience is

## Vision / Full Scope

The server should be Thomas's entire runtime surface — web, mobile, API, and
eventually desktop-native. Every interaction with Thomas flows through here.
The priority order for what should work well:

1. **Chat** — the core conversation experience. Must be fast, streaming, and
   feel like talking to your robot assistant.
2. **Memory** — cross-session, detailed, personal. Thomas should remember
   everything you tell it and bring it up when relevant.
3. **Plugins/Marketplace** — extend Thomas with installable capabilities.
   Already partially working.
4. **Mission/Goals** — autonomous task execution. Thomas should be able to
   work on things in the background.
5. **Companion** — mobile access to your assistant.
6. **Gateway** — let other tools talk to Thomas via OpenAI-compatible API.

## Do Not Touch

- `web/js/app_parts/` — dead code, agents are explicitly told to use
  `app_runtime_primary.mjs` instead. Don't edit, don't delete without
  explicit user approval.
- `swarm_mode.py` — compatibility shim only. Real code is in `thomas/agent/swarm`.
- `desktop_plugins.py` — this is a facade. Edit `_manifest.py` or `_runtime.py`.
