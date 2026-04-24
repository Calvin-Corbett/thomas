# Thomas Feature Catalog

Canonical index of major public Thomas capability areas. For implementation
status and user-facing readiness, use `docs/FUNCTIONALITY_INVENTORY.md`.

## Interfaces

- [ui.web_chat] Browser chat UI with streaming progress, model switching, setup guidance, and mode controls. (Paths: `thomas/server/web/index.html`, `thomas/server/web/js/`)
- [ui.repl_cli] Terminal-first interface for chat, commands, and diagnostics. (Paths: `thomas/cli/main.py`, `thomas/cli/repl.py`)
- [ui.live_browser_smoke] Visible browser automation smoke flow through CDP for local UI validation. (Paths: `thomas/cli/live_browser.py`)
- [ui.mission_control_workspace] Mission Control workspace for agents, jobs, approvals, and live activity stream updates. (Paths: `thomas/server/web/mission.html`, `thomas/server/web/mission.js`, `thomas/server/routes/mission.py`)
- [integration.telegram] Telegram bot channel with per-chat memory/session persistence and allowlist controls. (Paths: `thomas/integrations/telegram.py`, `thomas/cli/main.py`)
- [realtime.voice_ws] Realtime voice/websocket assistant surface with STT/TTS integration points. (Paths: `thomas/realtime/ws_handler.py`, `thomas/server/web/realtime/`)

## Agent And Execution

- [agent.intent_routing] Per-turn routing policy that selects mode, tools, and memory budget by intent path. (Paths: `thomas/agent/routing.py`)
- [agent.multi_mode_execution] Execution modes `fast`, `auto`, `thinking`, `swarm`, and `batch` across UI/server flow. (Paths: `thomas/agent/loop.py`, `thomas/server/`)
- [tools.registry_and_execution] Unified tool registry and execution adapters for filesystem, shell, git, search, diff, browser, and domain tools. (Paths: `thomas/tools/`)
- [guardrails.policy_and_approvals] Guardrails policy, approval broker, and tool gating with audit support. (Paths: `thomas/policy/`, `thomas/agent/guarded_tools.py`, `thomas/agent/approval.py`)

## Autonomy Platform

- [autonomy.jobs_engine] Background autonomy engine with scheduler, retries, lock recovery, and policy gates. (Paths: `thomas/autonomy/engine.py`, `thomas/autonomy/scheduler.py`, `thomas/autonomy/store.py`)
- [autonomy.objective_state_machine] Persistent objective/step state machine for long-horizon autonomy tracking. (Paths: `thomas/autonomy/models.py`, `thomas/autonomy/store.py`)
- [autonomy.workflow_task] Workflow execution patterns with chain, parallel, routing, and evaluator-optimizer support. (Paths: `thomas/autonomy/workflows.py`)
- [autonomy.media_jobs] Media-oriented autonomy handlers for video generation, transcription, and speech synthesis. (Paths: `thomas/autonomy/media_agents.py`)
- [autonomy.objective_api] Autonomy HTTP API and UI for jobs, approvals, objectives, and steps. (Paths: `thomas/autonomy/api.py`, `thomas/autonomy/ui/`)

## Model Platform

- [model.discovery_handshake] Provider model discovery and health checks. (Paths: `thomas/models/discovery.py`, `thomas/server/`)
- [model.protocol_validation] Model onboarding validation and tool-smoke protocol checks. (Paths: `thomas/models/protocol.py`, `scripts/check_model_onboarding_gate.py`)
- [model.capability_registry] Capability map per provider/profile for routing and UI visibility. (Paths: `thomas/models/capabilities.py`)
- [model.batch_chat_mode] Long-horizon async chat path using provider batch APIs. (Paths: `thomas/models/batching.py`)

## Memory And Knowledge

- [memory.thread_and_global] Thread-scoped episodic memory with curated global facts/profile hints. (Paths: `thomas/memory/autonomy.py`, `thomas/memory/store.py`, `thomas/memory/retrieval.py`)
- [memory.fabric_v2] Advanced memory fabric with retrieval scoring, contradiction tracking, and token-aware packing. (Paths: `thomas/memory/v2/`)
- [library.research_store] Durable research library with indexing, retrieval, and curation flows. (Paths: `thomas/library/store.py`, `library/`)

## Validation And Local Demos

- [validation.release_hygiene] Public-release hygiene checks for packaging, GitHub publish safety, and dependency surface. (Paths: `scripts/check_release_hygiene.py`, `scripts/github_publish_preflight.py`)
- [validation.browser_smoke] Local visible browser smoke tests for UI and tool behavior. (Paths: `thomas/cli/live_browser.py`, `tests/`)
- [validation.docker_smoke] Container build/import smoke path used by public CI. (Paths: `Dockerfile`, `.github/workflows/robustness-gates.yml`)

## Server, Security, And Operations

- [server.remote_access_control] Local/remote access modes with API token and request rate limiting. (Paths: `thomas/server/`, `docs/ops/GATEWAY_SECURITY_RUNBOOK.md`)
- [security.secret_storage] Provider secret management for API keys. (Paths: `thomas/server/secrets.py`)
- [observability.run_store_and_journal] Run/event persistence with filtering and retention controls. (Paths: `thomas/observability/`)
- [upgrade.doppelganger] Blue/green upgrade workflow and rollback controls. (Paths: `thomas/upgrade/doppelganger.py`, `thomas/cli/main.py`)
