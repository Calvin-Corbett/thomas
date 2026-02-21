# OpenClaw Parity Plan (Thomas)

> Historical note (2026-02-20): this file is a prior planning artifact.
> Current reality and tracked gaps are maintained in:
> - `docs/OPENCLAW_GAP_CHANGELOG.md`
> - `docs/OPENCLAW_CATCHUP_PROMPT_PACK_2026-02-20.md`

Date: 2026-02-11

## Goal
Match or exceed OpenClaw on:
- routing + failover reliability
- memory architecture
- channel consistency (Telegram/web/CLI)
- token efficiency and cost control

## External Baseline (OpenClaw)
- Two-layer memory: episodic timeline + profile memory with retrieval fusion.
- Multi-stage model routing and failover.
- Per-turn usage tracking with token/accounting surfaces.
- Telegram channels mapped to session IDs with deterministic routing options.

## Thomas Status (Current)
- Route-first agent policy with path-specific memory/tool budgets is active.
- Cross-profile LLM failover with cooldown and auth policy is active.
- Unified memory runtime is active across channels (legacy + Fabric v2).
- Telegram applies thread memory policy and can include global/profile memory.
- New `library/` subsystem stores long-form research outside chat memory and
  injects context only for research-oriented routes.
- Curator pipeline is active:
  - incremental checkpoints for episodes + library entries
  - confidence-gated promotion to semantic facts/profile hints
  - dedupe ledger for idempotent runs
- Contradiction review queue is active via API/UI:
  - list open contradictions
  - resolve reviewed contradictions

## Why This Architecture Is Correct
- Long-form research should not live in always-on memory packs; it should be
  stored durably and retrieved only when relevant.
- Profile/global memory should remain compact and high-signal.
- Route-gated retrieval lowers token burn while preserving response quality.

## Remaining Work To Exceed OpenClaw
Engineering gap is now implemented; benchmark verification is still pending.

- [x] Curator pipeline:
  - allow/deny approval workflows for promoted hints/facts via queue + decision APIs.
- [x] Source quality model:
  - trust score by source domain/type and recency decay feeding promotion confidence and retrieval ranking.
- [x] Memory governance:
  - contradiction review workflows with severity routing (`low/medium/high`, `standard/urgent`).
- [x] Cost controls:
  - automatic context compaction triggers based on `token_report` thresholds.
- [ ] Evidence:
  - benchmark and win-gate proof against pinned OpenClaw baseline.

## Suggested Implementation Sequence
1. Add contradiction approval workflows and admin policy controls.
2. Add trust/recency ranking features to retrieval.
3. Add source trust + contradiction severity routing.
4. Add adaptive compaction policy and dashboards.

## Priority Tracker (Started 2026-02-19)

Top priority: remove high-visibility feature gaps vs OpenClaw and keep a
single check-off list in-repo.

- [x] CLI cloud auth parity: `thomas chat --model anthropic` now overlays
  SecretStore keys before LLM init.
- [x] Webhook runtime wiring: webhook handlers are now bridged into the aiohttp
  server (management + receive routes).
- [x] Add first-class `webhooks` CLI surface (list/show/register/delete/stats/inbox).
- [x] Add first-class `sessions` CLI command (local persisted sessions listing).
- [x] Add first-class `channels` CLI surface (list/status for current channel integrations).
- [x] Add first-class `cron` CLI surface (status/list/add/remove/run over local scheduler).
- [x] Multi-agent CLI parity (`agents` command family: list/status/start/stop).
- [x] Device-pairing CLI parity (`devices` command family: list/pair/verify/revoke/status).
- [x] Sandbox CLI parity (`sandbox` command family: status/run/test).
- [x] Plugin lifecycle parity (`plugins` command family: list/install/show/enable/disable/uninstall).
- [x] OpenClaw name-compat command aliases for remaining top-level families (`acp`, `agent`, `approvals`, `browser`, `clawbot`, `completion`, `configure`, `daemon`, `directory`, `dns`, `docs`, `hooks`, `logs`, `memory`, `message`, `node`, `nodes`, `onboard`, `pairing`, `qr`, `reset`, `security`, `setup`, `skills`, `system`, `tui`, `uninstall`, `update`).
- [x] Executable alias upgrades for high-traffic families: `agent` now wraps `chat`, `browser` exposes smoke/status helpers, `logs` tails gateway logs, `help` prints CLI help, and `message` has local send/list/mark-sent queue flows.
- [x] Message behavior parity hardening: `message send --deliver` now performs real provider delivery attempts (Telegram/Discord/Slack) and persists `delivered`/`failed` status; `message retry` added for redelivery.
- [x] Top-level CLI command-name parity with OpenClaw baseline (`openclaw --help` names are all recognized in `thomas --help`; Thomas also keeps extra platform-specific commands).
- [x] Full channel provider parity (beyond Telegram): added Discord + Slack provider surfaces with configure/list/status/test and env-precedence.
- [x] Channel health hardening: `channels test --online` now validates provider semantics (Telegram/Discord/Slack auth payloads), not only HTTP status.
- [x] Dashboard/gateway lifecycle parity (`dashboard`, `gateway`, `status`, `health` command families).
- [x] Token-waste guard hardening: added per-iteration high prompt-spend runaway detection for repeated failing tool loops (beyond provider TPM controls).
- [x] CLI anti-monolith hardening for parity surfaces: split `main.py` command families and moved executable compat aliases into `parity_compat.py` while preserving command behavior.
- [x] Server anti-monolith hardening for parity surfaces: moved Codex HTTP endpoints and core route-table wiring out of `thomas/server/app.py` into dedicated aiohttp route modules.
- [x] Chat-run compatibility hardening: `/api/chat` now adapts `AgentLoop.run()` kwargs to the runtime signature to prevent legacy loop adapters from failing on new controls (for example `token_economy`).
- [x] Batch-mode server hardening: extracted `/api/chat` batch-mode execution into `thomas/server/chat_batch_mode.py` to reduce route-monolith risk while preserving stream/event parity.
- [x] UI-control server hardening: extracted `/api/chat` UI-control orchestration into `thomas/server/chat_control_mode.py` to keep settings/model/mode update behavior stable while reducing monolith risk.
- [x] Curator approval governance: added queue/decision workflows for promoted facts/hints (`/api/memory/curator/approvals`).
- [x] Contradiction governance hardening: added severity routing + explicit review decisions (`/api/memory/contradictions/review`).
- [x] Source-quality + recency scoring: library promotions now weight domain trust/type + staleness decay before memory promotion.
- [x] Token-report compaction guard: `/api/chat` and swarm mode now trigger memory compaction when token pressure crosses policy thresholds.
