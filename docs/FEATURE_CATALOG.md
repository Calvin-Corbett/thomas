# Thomas Feature Catalog

Canonical source of truth for major Thomas capabilities.

Use this file when planning work, writing prompts, or reviewing scope so you do not need to re-scan the full codebase.

Update rule:
- Any PR that adds, removes, or materially changes a major feature must update this catalog in the same PR.

## How To Read

- Format: `feature_id` + one-line summary + primary implementation paths.
- Purpose: fast map of what Thomas already has.
- Scope: major platform capabilities (not every helper/internal function).

## Interfaces

- [ui.web_chat] Browser chat UI with streaming progress, jobs inspector, model switching, and mode controls. (Paths: `thomas/server/web/index.html`, `thomas/server/web/js/chat.js`, `thomas/server/web/js/app.js`)
- [ui.repl_cli] Terminal-first interface for chat, model commands, and diagnostics. (Paths: `thomas/cli/main.py`, `thomas/cli/repl.py`)
- [ui.live_browser_smoke] Visible browser automation smoke flow through CDP for end-to-end UI validation. (Paths: `thomas/cli/live_browser.py`)
- [ui.mission_control_workspace] Unified live workspace view for agents/runs/jobs with room movement, on-demand virtual-office floorplan (desks + rooms), model-coded agent identities, activity popup, operator actions, and live NDJSON stream updates (`/api/mission/stream`). (Paths: `thomas/server/web/mission.html`, `thomas/server/web/mission.js`, `thomas/server/app.py`)
- [integration.telegram] Telegram bot channel with per-chat memory/session persistence and allowlist controls. (Paths: `thomas/integrations/telegram.py`, `thomas/cli/main.py`)
- [realtime.voice_ws] Realtime voice/websocket assistant surface with STT/TTS and latency budgets. (Paths: `thomas/realtime/ws_handler.py`, `thomas/server/web/realtime/realtime.js`)

## Agent And Execution

- [agent.intent_routing] Per-turn routing policy selecting mode/tools/memory budget by intent path. (Paths: `thomas/agent/routing.py`)
- [agent.multi_mode_execution] Execution modes `fast`, `auto`, `thinking`, `swarm`, and `batch` across UI/server flow. (Paths: `thomas/agent/loop.py`, `thomas/server/app.py`)
- [tools.registry_and_execution] Unified tool registry and execution adapters for filesystem/shell/git/search/diff. (Paths: `thomas/tools/registry.py`, `thomas/tools/*.py`)
- [guardrails.policy_and_approvals] Guardrails policy, approval broker, and tool gating with audit support. (Paths: `thomas/policy/*.py`, `thomas/agent/guarded_tools.py`, `thomas/agent/approval.py`)

## Autonomy Platform

- [autonomy.jobs_engine] Background autonomy engine with scheduler, retries, lock recovery, and policy gates. (Paths: `thomas/autonomy/engine.py`, `thomas/autonomy/scheduler.py`, `thomas/autonomy/store.py`)
- [autonomy.objective_state_machine] Persistent objective/step state machine for long-horizon autonomy tracking. (Paths: `thomas/autonomy/models.py`, `thomas/autonomy/store.py`, `thomas/autonomy/engine.py`)
- [autonomy.workflow_task] Workflow execution patterns (chain/parallel/routing/evaluator-optimizer) with fallback behavior. (Paths: `thomas/autonomy/workflows.py`, `thomas/autonomy/engine.py`)
- [autonomy.media_jobs] Media-oriented autonomy job handlers for video generation, transcription, and speech synthesis. (Paths: `thomas/autonomy/media_agents.py`, `thomas/autonomy/engine.py`)
- [autonomy.objective_api] Autonomy HTTP API + UI for jobs, approvals, objectives, and steps. (Paths: `thomas/autonomy/api.py`, `thomas/autonomy/ui/*`)

## Model Platform

- [model.discovery_handshake] Provider model discovery and handshake health checks. (Paths: `thomas/models/discovery.py`, `thomas/server/app.py`)
- [model.protocol_validation] Strict model onboarding validation and tool-smoke protocol checks. (Paths: `thomas/models/protocol.py`, `scripts/forge/gates/model_onboarding_gate.py`)
- [model.capability_registry] Capability map per provider/profile for routing and UI visibility. (Paths: `thomas/models/capabilities.py`, `thomas/server/app.py`)
- [model.batch_chat_mode] Long-horizon async chat path using provider batch APIs. (Paths: `thomas/models/batching.py`, `thomas/server/app.py`)

## Memory And Knowledge

- [memory.thread_and_global] Thread-scoped episodic memory with curated global facts/profile hints. (Paths: `thomas/memory/autonomy.py`, `thomas/memory/store.py`, `thomas/memory/retrieval.py`)
- [memory.fabric_v2] Advanced memory fabric with retrieval scoring, contradiction tracking, and token-aware packing. (Paths: `thomas/memory/v2/*.py`)
- [library.research_store] Durable research library with indexing, retrieval, and curation flows. (Paths: `thomas/library/store.py`, `library/*`)

## Benchmarking And Demos

- [demo.head_to_head_harness] Structured head-to-head scoring harness with reproducible artifacts and aggregation. (Paths: `thomas/demo/harness.py`, `scripts/run_head_to_head_demo.py`, `demo/task_pack.default.json`)
- [demo.dual_browser_runner] Automated dual-browser timestamped execution against competitor targets. (Paths: `thomas/demo/browser_duel.py`, `scripts/run_dual_browser_demo.py`)
- [demo.multi_run_campaign] Campaign-level multi-run execution, aggregate scorecards, and publish pack output. (Paths: `thomas/demo/campaign.py`, `scripts/run_demo_campaign.py`)

## Server, Security, And Operations

- [server.remote_access_control] Local/remote access modes with API token and request rate limiting. (Paths: `thomas/server/app.py`)
- [security.secret_storage] Secure provider secret management for API keys. (Paths: `thomas/server/secrets.py`)
- [observability.run_store_and_journal] Run/event persistence with filtering and retention controls. (Paths: `thomas/observability/run_store.py`, `thomas/observability/journal.py`)
- [forge.anvil.doppelganger] Blue/green upgrade workflow and rollback controls. (Paths: `thomas/forge/anvil/doppelganger.py`, `thomas/cli/main.py`)

## observability.run_replay

**Goal:** Deterministic run replay for chat/autonomy runs.

**What it adds**
- Persist replayable event streams (HTTP run context + best-effort auto-instrument for model/tool calls).
- Replay control APIs (served from `thomas/server/routes/runs.py`):
  - `GET /api/runs/{run_id}/events` (paged)
  - `POST /api/runs/{run_id}/replay/seek`
  - `POST /api/runs/{run_id}/replay/step`
  - `GET /api/runs/{run_id}/replay_stream?from=&speed=` (NDJSON stream w/ optional timing)
  - `GET /api/runs/{run_id}/export.json` (shareable JSON replay artifact)
- Redaction layer on all replay payloads (secrets never appear in API/UI replay responses).

**Note:** The standalone `replay_debugger.py` route module was removed in v0.11.73 — all replay functionality lives in `runs.py`.
