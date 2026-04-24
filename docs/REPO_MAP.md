# Thomas Repo Map

Use this as a fast directory guide. It explains what lives where and whether a
new contributor or agent should treat the area as product code, docs, tests, or
maintenance infrastructure.

## Top-Level Paths

| Path | Purpose | Notes |
|---|---|---|
| `.github/` | GitHub Actions, issue templates, PR template, and agent guidance. | Public release checks live here. |
| `agents/` | Agent and automation definitions used by Thomas workflows. | Inspect status before changing behavior. |
| `apps/` | Companion/client app surfaces and supporting app experiments. | Not all app surfaces are first-run product paths. |
| `assets/` | Static assets used by runtime, UI, or packaging. | Avoid adding large generated assets without need. |
| `cli/` | CLI entry helpers and command wiring. | Most user-facing CLI behavior is also under `thomas/cli/`. |
| `definitions/` | Task, schema, and workflow definitions. | Treat as product configuration, not scratch space. |
| `docs/` | Public docs, architecture, operations, support, and release guidance. | Start with `DOCUMENTATION_INDEX.md`. |
| `extensions/` | Extension and integration support code. | Verify extension tests before changing. |
| `installer/` | Windows installer assets and packaging support. | Keep installer claims synced with release tests. |
| `library/` | Local library/research storage area and examples. | Runtime state should stay out of git unless intentional. |
| `plugins/` | Packaged plugin examples and manifests. | Some plugins are scaffolds; check `docs/FEATURE_MATRIX.md`. |
| `prompt_pack/` | Prompt and compatibility assets. | Changes can affect model/provider behavior. |
| `scripts/` | Release, hygiene, setup, diagnostics, and maintenance helpers. | Prefer existing scripts over new one-off automation. |
| `server/` | Server-adjacent compatibility and support paths. | Main server package is under `thomas/server/`. |
| `skills/` | Thomas-specific skill/runtime support that is safe for public release. | Do not add local personal skills or deployment-only private helpers. |
| `tests/` | Unit, integration, release, installer, and surface tests. | Use focused tests for fast validation, then public gates before release. |
| `thomas/` | Core product runtime. | Main package for server, web UI, tools, memory, policy, autonomy, companion, and marketplace modules. |

## Core Runtime Areas

| Path | Purpose |
|---|---|
| `thomas/agent/` | Agent loop, routing, guarded tools, approvals, and execution flow. |
| `thomas/autonomy/` | Jobs engine, scheduler, objective state, workflow handlers, and autonomy APIs. |
| `thomas/chat/` | Conversation handling, context, and chat runtime pieces. |
| `thomas/cli/` | `thomas` command group, REPL, diagnostics, evolve commands, and companion commands. |
| `thomas/companion/` | Companion kernel, contracts, module updates, devices, releases, audit, and policy scaffolding. |
| `thomas/core/` | Shared config, model support, persistence, routing primitives, and common services. |
| `thomas/library/` | Research/library store and indexing/retrieval plumbing. |
| `thomas/marketplace/` | Broad domain modules. Many are Partial or Prototype; validate before public claims. |
| `thomas/memory/` | Memory store, retrieval, advanced fabric, and token-aware packing. |
| `thomas/models/` | Provider discovery, protocol validation, capability registry, and batch chat support. |
| `thomas/observability/` | Run store, journal, replay/export, and debugging support. |
| `thomas/policy/` | Guardrails, policy checks, and tool/use restrictions. |
| `thomas/realtime/` | Voice and websocket assistant surfaces. |
| `thomas/server/` | Aiohttp app, middleware, routes, secrets, preferences, static web UI, and startup behavior. |
| `thomas/tools/` | Built-in tools for filesystem, shell, git, search, browser, database, email/calendar, and domain actions. |

## Public-Release Guardrails

| Path | Why it matters |
|---|---|
| `.github/workflows/github-publish-safety.yml` | Runs public publish safety checks. |
| `.github/workflows/windows-installer.yml` | Builds and smoke-tests the Windows installer release asset. |
| `scripts/github_publish_preflight.py` | Blocks secrets, private paths, stale public surfaces, and unsafe config. |
| `scripts/check_repo_hygiene.py` | Keeps repo shape and dirty-worktree state under control. |
| `docs/repo_hygiene_baseline.json` | Baseline used by repo hygiene checks. |
| `tests/test_public_release_surface.py` | Public-surface regression checks. |
| `tests/test_public_repo_guidance.py` | Checks that public onboarding and GitHub guidance exist. |

## Runtime State Policy

Runtime state belongs outside committed source unless a file is an intentional
fixture or template. Do not commit local `.venv`, logs, support ZIPs, cache
folders, generated reports, local database files, or personal notes.
