# Thomas Functionality Inventory

This inventory is the public map of what Thomas contains and how ready each area
is. Status words are intentionally plain:

- Stable: expected to work in the public release path.
- Beta: works, but still needs polish, coverage, or clearer UX.
- Partial: meaningful code exists, but the user experience is incomplete.
- Prototype: scaffold or early implementation; do not treat as dependable.
- Internal: maintainer/developer support surface, not a normal user feature.

## User-Facing Surfaces

| Area | Capability | Status | Notes |
|---|---|---|---|
| Install | `run-ui.cmd`, `setup.cmd`, `repair.cmd`, `bootdoctor.cmd` | Stable | Primary Windows path. Creates `.venv` inside the repo and installs local runtime dependencies. |
| Web UI | Browser chat workspace | Beta | Main user surface. Starts locally and supports setup, chat, model controls, progress, and tool/result display. |
| Easy Setup | First-run model/provider setup | Beta | Guides users into Codex, local, or API-backed profiles. Some provider flows still depend on external credentials being ready. |
| CLI | `thomas` command group and REPL | Beta | Useful for diagnostics and advanced use. Non-engineer UX is less polished than the browser UI. |
| Mission Control | Jobs, objectives, approvals, live activity | Beta | Real route/UI surface. Good for inspecting background work, but still evolving. |
| Memory | Thread/global memory and retrieval | Beta | Stores and retrieves context. Advanced memory fabric exists but needs careful UX and privacy review. |
| Guardrails | Tool approvals, policy checks, local-only protections | Beta | Active safety layer for tool execution and mutating routes. Some policies are conservative by design. |
| Tools | Filesystem, shell, git, browser, search, diff, and domain tools | Beta | Tool registry is broad. Individual domain tools vary in maturity. |
| Integrations | Telegram, Discord bridge, Google Workspace, email/calendar-style modules | Partial | Some integrations are functional with credentials; setup and public docs are uneven. |
| Desktop/Tray | Tray agent and local desktop helper paths | Partial | Useful for local operation, but not the recommended first-run path. |
| Voice/Realtime | Websocket voice/realtime assistant surfaces | Partial | Code and UI hooks exist; production readiness depends on provider credentials and latency path. |
| Life Manager plugin | Tasks, agenda, habits, goals | Beta | Optional plugin-backed personal productivity surface. State is local. |
| Asset Studio | Media/asset workflow hooks | Partial | Multiple connectors exist; end-to-end UX is still rough. |
| Browser automation | Browser action/artifact commands | Beta | CLI and internal tool support exists for screenshots, DOM snapshots, accessibility snapshots, and browser control. |
| Evolve mode | Self-improvement sessions and promotion workflow | Beta | CLI and mission-job support exist with tests. Treat as guarded advanced mode, not a beginner feature. |

## Backend And Runtime

| Area | Capability | Status | Notes |
|---|---|---|---|
| Server | Aiohttp app, route modules, middleware | Beta | Main local runtime. Public default is loopback-only. |
| Access control | Local/remote mode, API token, CSRF protection, rate limit hooks | Beta | Remote deployment requires explicit production configuration. |
| Model platform | Discovery, protocol validation, capability registry, batch mode | Beta | Core model routing exists; exact behavior depends on provider/profile setup. |
| Secrets | Provider secret storage | Beta | Public release should never include real credentials. Users configure their own. |
| Observability | Run store, journal, replay/export hooks, health endpoints | Beta | Useful for debugging; some views are maintainer-oriented. |
| Autonomy | Jobs engine, scheduler, objectives, retries, workflows | Beta | Real runtime exists; users should start with supervised jobs and approvals. |
| Plugin system | Manifest loading, lifecycle commands, hooks, marketplace catalog | Beta | Broad surface. Some packaged plugin folders are examples or scaffolds. |
| Companion API | Device/companion policy and routes | Partial | Public code exists; app-store/device release path is not first-run ready. |
| Gateway/API compatibility | Gateway commands, OpenAI-style request/response route support | Partial | Useful for advanced users. Needs more public examples before calling it stable. |
| Data/library | Local library and research-store plumbing | Partial | Durable storage exists. Public workflows need clearer guidance. |
| Repair/doctor | Boot diagnostics and startup recovery | Stable | Important support path when install or startup fails. |
| Packaging | Dockerfile, installer assets, release hygiene checks | Beta | Docker smoke and packaging checks run in CI; installer publishing still needs maintainer steps. |

## Domain And Marketplace Modules

Thomas includes many domain modules under `thomas/marketplace/`. These are not all equal in readiness.

| Category | Examples | Status | Notes |
|---|---|---|---|
| Core-adjacent | channels, companion, containers, dns, nodes, workflow, notifications | Beta/Partial | Closest to real product workflows. |
| Developer/platform | codegen, devops, gateway, monitoring, logging, tracing, service mesh | Partial | Useful scaffolds and tools, uneven end-to-end UX. |
| Business/domain | CRM, ERP, finance, travel, ecommerce-style modules | Prototype/Partial | Mostly toolkit modules; not a finished vertical product. |
| Media/creative | asset studio, audio, image/video-adjacent helpers, 3D/CAD | Prototype/Partial | Some useful connectors; needs curation before beginner use. |
| Security/ops | audit, guardrail-adjacent modules, policy, WAF, SIEM-style helpers | Partial | Treat as helper tooling, not a certified security product. |

## Removed From Public Release

These surfaces were intentionally removed from the public branch:

- Private release history before `0.14.59`.
- Old comparison packs, scoreboards, and generated test-output baselines.
- Private website deployment surface and provider-specific deployment skills.
- Agent handoff logs, orphan inventories, stale module-audit logs, and pre-public cleanup notes.
- Archived domain experiments that were not imported by the runtime.

## Guidance For AI Agents Reading This Repo

Start with these files in order:

1. `README.md` for install and first-run behavior.
2. `docs/FUNCTIONALITY_INVENTORY.md` for capability status.
3. `docs/NETWORKING_AND_FIREWALL.md` for local/remote network posture.
4. `DOCUMENTATION_INDEX.md` for stable docs.
5. `docs/PROJECT_SCOPE.md` for public-release boundaries.

Do not infer that every module under `thomas/marketplace/` is production-ready. Use the status labels above and inspect tests before changing a specific area.
