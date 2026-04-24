# Thomas Documentation Index

This index points to the stable docs that make sense in the public release. Use it to find the right starting point without digging through internal notes or automation files.

## Start Here

- [`README.md`](README.md) - install, first run, and public-release orientation
- [`docs/AGENT_START_HERE.md`](docs/AGENT_START_HERE.md) - fastest safe route for AI agents and contributors
- [`docs/FEATURE_MATRIX.md`](docs/FEATURE_MATRIX.md) - public feature/status matrix with audience, entry points, and evidence
- [`docs/REPO_MAP.md`](docs/REPO_MAP.md) - top-level directory map and runtime area guide
- [`docs/ARCHITECTURE_OVERVIEW.md`](docs/ARCHITECTURE_OVERVIEW.md) - install, runtime, guardrail, and companion architecture diagrams
- [`docs/ROADMAP.md`](docs/ROADMAP.md) - public roadmap, Infinite app direction, and Thomas OS concept notes
- [`SECURITY.md`](SECURITY.md) - security policy and disclosure process
- [`CHANGELOG.md`](CHANGELOG.md) - release history and notable behavior changes
- [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md) - known limitations and active rough edges
- [`docs/FUNCTIONALITY_INVENTORY.md`](docs/FUNCTIONALITY_INVENTORY.md) - public capability map and readiness status
- [`docs/NETWORKING_AND_FIREWALL.md`](docs/NETWORKING_AND_FIREWALL.md) - local-first networking and firewall guidance

## Install, Repair, and Deploy

- [`docs/WINDOWS_INSTALLER_GUIDE.md`](docs/WINDOWS_INSTALLER_GUIDE.md) - Windows installer build and packaging
- [`docs/NETWORKING_AND_FIREWALL.md`](docs/NETWORKING_AND_FIREWALL.md) - firewall prompts, loopback defaults, and remote-access boundaries
- [`docs/ops/DOCKER_DEPLOY.md`](docs/ops/DOCKER_DEPLOY.md) - Docker deployment and runtime notes
- [`docs/ops/GATEWAY_SECURITY_RUNBOOK.md`](docs/ops/GATEWAY_SECURITY_RUNBOOK.md) - gateway security and incident-response guidance
- [`docs/ops/RETRY_POLICY.md`](docs/ops/RETRY_POLICY.md) - retry behavior, failure handling, and backoff expectations
- [`docs/GITHUB_PUBLISH_SAFETY_WORKFLOW.md`](docs/GITHUB_PUBLISH_SAFETY_WORKFLOW.md) - maintainer workflow for preparing public releases

## Architecture and Code Areas

| Area | Doc or Path | Purpose |
|---|---|---|
| Runtime overview | [`thomas/README.md`](thomas/README.md) | Map of the core runtime modules |
| Repo map | [`docs/REPO_MAP.md`](docs/REPO_MAP.md) | Top-level folder guide for humans and agents |
| Architecture overview | [`docs/ARCHITECTURE_OVERVIEW.md`](docs/ARCHITECTURE_OVERVIEW.md) | High-level install, runtime, and companion diagrams |
| Capability inventory | [`docs/FUNCTIONALITY_INVENTORY.md`](docs/FUNCTIONALITY_INVENTORY.md) | Feature status and user-facing readiness |
| Feature matrix | [`docs/FEATURE_MATRIX.md`](docs/FEATURE_MATRIX.md) | Capability status with audience, entry points, and evidence |
| Chat flow | [`docs/CHAT_EXECUTION_MODEL.md`](docs/CHAT_EXECUTION_MODEL.md) | End-to-end request and execution flow |
| Chat and sessions | [`thomas/chat/README.md`](thomas/chat/README.md) | Conversation handling and context |
| Core services | [`thomas/core/README.md`](thomas/core/README.md) | Config, models, events, and shared runtime services |
| Memory | [`thomas/memory/README.md`](thomas/memory/README.md) | Memory, retrieval, embeddings, and storage |
| Tools | [`thomas/tools/README.md`](thomas/tools/README.md) | Tool interfaces and built-in implementations |
| Server | [`thomas/server/README.md`](thomas/server/README.md) | Aiohttp server, middleware, and boot flow |
| API routes | [`thomas/server/routes/README.md`](thomas/server/routes/README.md) | Route organization and HTTP surface |
| Web UI | [`thomas/server/web/README.md`](thomas/server/web/README.md) | Frontend runtime, assets, and browser behavior |
| Orchestration | [`thomas/orchestrator/`](thomas/orchestrator/) | Routing and orchestration code |
| Specialists | [`thomas/specialists/`](thomas/specialists/) | Specialist implementations used by orchestration |
| Scripts | [`scripts/README.md`](scripts/README.md) | Packaging, hygiene, automation, and checks |
| Clients and companion apps | [`apps/`](apps/) | Companion/client surfaces shipped alongside the runtime |
| Infinite app roadmap | [`docs/THOMAS_INFINITE.md`](docs/THOMAS_INFINITE.md) and [`docs/ROADMAP.md`](docs/ROADMAP.md) | Planned private mobile companion direction |

## Common Tasks

- Run Thomas locally: start with [`README.md`](README.md).
- Fix setup or a broken environment: use `repair.cmd`, `bootdoctor.cmd`, and [`docs/WINDOWS_INSTALLER_GUIDE.md`](docs/WINDOWS_INSTALLER_GUIDE.md).
- Trace chat behavior: read [`docs/CHAT_EXECUTION_MODEL.md`](docs/CHAT_EXECUTION_MODEL.md) and [`thomas/chat/README.md`](thomas/chat/README.md).
- Change the web UI: read [`thomas/server/web/README.md`](thomas/server/web/README.md).
- Add or modify an API endpoint: read [`thomas/server/routes/README.md`](thomas/server/routes/README.md).
- Add or modify a tool: read [`thomas/tools/README.md`](thomas/tools/README.md).
- Work on memory or retrieval: read [`thomas/memory/README.md`](thomas/memory/README.md).
- Package or publish the app: use [`installer/`](installer/) and [`docs/WINDOWS_INSTALLER_GUIDE.md`](docs/WINDOWS_INSTALLER_GUIDE.md).
- Hand an AI agent a task: start with [`docs/AGENT_START_HERE.md`](docs/AGENT_START_HERE.md), [`docs/FEATURE_MATRIX.md`](docs/FEATURE_MATRIX.md), and the GitHub agent task issue template.
- Understand the roadmap: read [`docs/ROADMAP.md`](docs/ROADMAP.md) and [`docs/THOMAS_INFINITE.md`](docs/THOMAS_INFINITE.md).

## Notes

- Some directories under `thomas/` are long-term scaffolds rather than fully implemented user-facing modules.
- The repo still contains contributor-oriented docs and automation helpers. The links above are the stable entry set for the public release.
