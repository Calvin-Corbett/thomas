# Thomas Feature Matrix

This matrix is the public, agent-readable view of what Thomas contains today.
Use it with `docs/FUNCTIONALITY_INVENTORY.md` when deciding what is safe to
demo, test, fix, or extend.

Status words:

- Stable: expected to work in the public release path.
- Beta: real and usable, but still needs polish, coverage, or clearer UX.
- Partial: meaningful implementation exists, but the end-to-end user experience
  is incomplete.
- Prototype: scaffold or early implementation; do not treat as dependable.
- Planned: roadmap item with supporting direction, not shipped functionality.
- Internal: maintainer/developer support surface, not a normal user feature.

Audience words:

- User-facing: visible to a normal user.
- Agent-facing: intended to help coding/review agents understand or change the
  repo.
- Backend: runtime, API, policy, or packaging layer behind user workflows.
- Maintainer: release, safety, or operations path.

## Install, Support, And First Run

| Feature | Audience | Status | Entry points | Evidence | Notes |
|---|---|---|---|---|---|
| Windows installer | User-facing | Stable | `ThomasSetup_0.14.61.exe`, `installer/`, `.github/workflows/windows-installer.yml` | `tests/test_windows_installer_assets.py` | Recommended public install path. CI smoke-tests silent install and first-run wizard assets. |
| First-run wizard | User-facing | Stable | `scripts/first_run_wizard.ps1`, `scripts/first-run.cmd` | `tests/test_windows_installer_assets.py`, `tests/test_setup_wizard.py` | Creates local runtime state and hands off to browser Easy Setup. |
| Easy Setup | User-facing | Beta | `/api/setup/*`, web UI setup modal | `tests/test_server_setup_routes.py`, `tests/test_web_evolve_chat_ux.py` | Guides model/provider setup. Provider credentials still depend on the user's local environment. |
| Repair path | User-facing | Stable | `repair.cmd`, `setup.cmd`, `bootdoctor.cmd` | `tests/test_bootdoctor_cli.py`, `tests/test_launcher_boot_recovery_contract.py` | Main self-repair path for broken setup or startup state. |
| Support bundle | User-facing | Stable | `support.cmd`, `scripts/support_bundle.ps1` | `tests/test_support_bundle_script.py` | Creates a redacted diagnostic ZIP under `runtime\support\`. |
| Firewall guidance | User-facing | Stable | `docs/NETWORKING_AND_FIREWALL.md`, setup diagnostics | `tests/test_public_release_surface.py` | Explains why loopback startup can trigger Windows Firewall prompts. |

## Everyday Product Surfaces

| Feature | Audience | Status | Entry points | Evidence | Notes |
|---|---|---|---|---|---|
| Browser chat workspace | User-facing | Beta | `thomas/server/web/index.html`, `thomas/server/web/js/` | `tests/test_web_chat_surface_contract.py`, `tests/test_product_surface_copy.py` | Main UI for chat, setup, progress, model controls, memory, and tools. |
| Model switching | User-facing | Beta | `/api/models`, preferences routes, web settings | `tests/test_server_models_routes.py`, `tests/test_model_switching.py` | Supports configured profiles and provider discovery. |
| Conversation search | User-facing | Beta | `/api/search`, web search UI | `tests/test_conversation_search_v4.py`, `tests/test_server_search_routes.py` | Local search across stored conversations. |
| Memory | User-facing / Backend | Beta | `thomas/memory/`, memory routes | `tests/test_memory_system.py`, `tests/test_memory_fabric_v2.py` | Thread/global memory and advanced memory fabric exist; privacy UX still needs tightening. |
| Mission Control | User-facing | Beta | `/mission`, `thomas/server/routes/mission.py` | `tests/test_server_mission_control.py`, `tests/test_operator_mission_smoke.py` | Jobs, objectives, approvals, and live activity. |
| Builder controls | User-facing | Beta | web UI builder mode, settings surfaces | `tests/test_product_surface_copy.py` | Hidden behind safer everyday defaults until the user opts in. |
| Voice/realtime | User-facing | Partial | `thomas/realtime/`, web realtime UI | `tests/test_realtime_ws.py`, `tests/web/realtime_state.test.mjs` | Hooks exist; readiness depends on provider path and latency. |
| Desktop/tray helpers | User-facing | Partial | tray/desktop helper modules | `tests/test_desktop_operator_host_service.py`, `tests/test_desktop_operator_runtime.py` | Useful but not the recommended first-run path. |

## Agent, Tools, And Automation

| Feature | Audience | Status | Entry points | Evidence | Notes |
|---|---|---|---|---|---|
| Tool registry and execution | User-facing / Backend | Beta | `thomas/tools/`, `thomas/agent/guarded_tools.py` | `tests/test_tool_registry_resolution.py`, `tests/test_guarded_tool_runner.py` | Filesystem, shell, git, browser, search, diff, and domain tools. |
| Guardrails and approvals | User-facing / Backend | Beta | `thomas/policy/`, `thomas/agent/approval.py` | `tests/test_agent_loop_tool_policy.py`, `tests/test_guardrail_hardening.py` | Policy and approval checks before sensitive tool use. |
| Autonomy jobs engine | User-facing / Backend | Beta | `thomas/autonomy/`, Mission Control | `tests/test_autonomy_engine.py`, `tests/test_autonomy_store.py` | Long-running jobs, retries, lock recovery, and supervised execution. |
| Objectives and workflows | User-facing / Backend | Beta | `thomas/autonomy/models.py`, `thomas/autonomy/workflows.py` | `tests/test_autonomy_workflows.py`, `tests/test_workflow_engine.py` | Persistent objective and workflow primitives. |
| Evolve mode | User-facing / Maintainer | Beta | CLI evolve commands, autonomy evolve routes | `tests/test_cli_evolve_commands.py`, `tests/test_autonomy_engine_evolve.py` | Guarded self-improvement sessions. Advanced mode, not beginner UX. |
| Browser automation | User-facing / Backend | Beta | `thomas/tools/browser.py`, `thomas/cli/live_browser.py` | `tests/test_browser_tool_fast_lane.py`, `tests/test_browser_workflow_runtime.py` | Supports screenshots, DOM snapshots, accessibility snapshots, and local browser actions. |
| Plugin system | User-facing / Backend | Beta | `thomas/autonomy/plugin.py`, plugin manifests | `tests/test_plugin_catalog_index.py`, `tests/test_plugin_hosting.py` | Real module loading lifecycle; some packaged modules are examples or scaffolds. |
| Marketplace/domain modules | User-facing / Backend | Partial | `thomas/marketplace/` | domain-specific tests under `tests/` | Broad toolkit surface. Do not assume every vertical is finished. |

## Integrations And Data

| Feature | Audience | Status | Entry points | Evidence | Notes |
|---|---|---|---|---|---|
| Telegram channel | User-facing | Partial | `thomas/integrations/telegram.py` | `tests/test_telegram_integration.py` | Requires credentials and allowlist setup. |
| Discord bridge | User-facing | Partial | Discord route/runtime modules | `tests/test_discord_runtime_config.py`, `tests/test_discord_channel_routes.py` | Functional pieces exist; public setup is not beginner-ready. |
| Email and calendar tools | User-facing | Partial | `thomas/tools/email_calendar.py`, `docs/tools/email_calendar.md` | `tests/test_email_imap.py`, `tests/test_email_smtp.py` | Credentialed integration path with uneven beginner UX. |
| Library/research store | User-facing / Backend | Partial | `library/`, `thomas/library/` | `tests/test_library_store.py`, `tests/test_agent_loop_library.py` | Durable storage and retrieval plumbing exists; public workflows need more examples. |
| Provider secret storage | Backend | Beta | `thomas/server/secrets.py` | `tests/test_server_secrets_rotation.py` | Users configure their own credentials; public repo must not contain real secrets. |

## Operations, Packaging, And GitHub

| Feature | Audience | Status | Entry points | Evidence | Notes |
|---|---|---|---|---|---|
| Public publish preflight | Maintainer | Stable | `scripts/github_publish_preflight.py`, `.github/workflows/github-publish-safety.yml` | `tests/test_github_publish_preflight.py` | Blocks private artifacts, live secrets, unsafe config, and stale publish surfaces. |
| Repo hygiene gate | Maintainer | Stable | `scripts/check_repo_hygiene.py`, `docs/repo_hygiene_baseline.json` | `tests/test_repo_hygiene.py` | Protects public repo shape and dirty-worktree release mistakes. |
| Robustness gates | Maintainer | Beta | `.github/workflows/robustness-gates.yml` | `tests/test_ci_workflow_guards.py` | CI coverage for selected runtime and release checks. |
| Docker path | Maintainer | Beta | `Dockerfile`, `docs/ops/DOCKER_DEPLOY.md` | workflow checks | Useful for advanced deploy/testing, not the first public install path. |
| GitHub issue templates | Maintainer / Agent-facing | Stable | `.github/ISSUE_TEMPLATE/` | `tests/test_public_repo_guidance.py` | Keeps install failures, bugs, features, and agent tasks structured. |
| Agent onboarding docs | Agent-facing | Stable | `docs/AGENT_START_HERE.md`, `.github/copilot-instructions.md` | `tests/test_public_repo_guidance.py` | Gives agents a short, stable path through the large repo. |

## Roadmap And Future Product Surfaces

| Feature | Audience | Status | Entry points | Evidence | Notes |
|---|---|---|---|---|---|
| Infinite app | User-facing | Planned | `docs/THOMAS_INFINITE.md`, `docs/COMPANION_APP_INTEGRATION.md`, `docs/ROADMAP.md` | companion contract tests | Planned mobile companion for private Tailscale-connected chat, approvals, and Thomas-built app surfaces. |
| Companion app module updates | User-facing / Backend | Partial | `thomas/companion/`, `/api/companion/v1/*` | `tests/test_companion_contracts.py`, `tests/test_companion_update.py` | Backend contract and compliance scaffolding exist; app-store client is not shipped here. |
| App-grid/home-screen experience | User-facing | Planned | `docs/THOMAS_INFINITE.md`, `docs/ROADMAP.md` | none yet | Intended Infinite UX where Thomas-built app surfaces appear as launchable icons. |
| Thomas OS | User-facing | Planned | `docs/ROADMAP.md`, `docs/THOMAS_INFINITE.md` | none yet | Long-horizon concept only. Not an active OS distribution or installer. |
