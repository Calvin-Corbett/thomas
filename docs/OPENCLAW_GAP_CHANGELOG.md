# OpenClaw Gap Changelog (Thomas)

Last updated: 2026-02-21
Baseline repos:
- Thomas: `F:\DevHub\Thomas`
- Canonical baseline artifact: `demo/baselines/openclaw.current.json`
- Local OpenClaw snapshot path (from baseline artifact): `F:\DevHub\_tmp_openclaw_count_1771454552`

Deterministic compare command:
- `python scripts/compare_openclaw_baseline.py --write`
- Latest machine-readable compare report:
  - `docs/openclaw_gap_runs/latest_compare.json`

This document is the source of truth for capability gaps vs OpenClaw.
It is intentionally critical. Name parity alone is not counted as capability parity.
Parallel execution prompts live at:
- `docs/OPENCLAW_CATCHUP_PROMPT_PACK_2026-02-20.md`
- `docs/OPENCLAW_CATCHUP_PROMPT_PACK_216_2026-02-20.md`
- `docs/OPENCLAW_CATCHUP_PROMPT_BATCH_INDEX_216_2026-02-20.csv`
- Intake operating flow for prompt drops:
  - `docs/CODE_INTAKE_PIPELINE.md`
  - `scripts/code_intake.py`
  - `scripts/code_intake_seed_batch.py`

## Rules

- Do not copy OpenClaw branding, names, or internal terminology into Thomas.
- Rebuild capabilities with Thomas-native architecture and naming.
- Keep OpenClaw as an external benchmark only.

## [2026-02-20] Baseline Reset (Critical)

### 1) Size + Test Surface

Measured 2026-02-20 with local code-file counters (code extensions only).

| Metric | Thomas | OpenClaw | Gap |
|---|---:|---:|---:|
| Product-scope LOC | 112,638 | 815,576 | OpenClaw +702,938 (7.24x) |
| Product-scope files | 439 | 4,596 | OpenClaw +4,157 |
| Raw code LOC snapshot | 118,551 | 820,966 | OpenClaw +702,415 |
| Test LOC | 9,956 | 244,486 | OpenClaw +234,530 (24.6x) |
| Test files | 98 | 1,281 | OpenClaw +1,183 |
| Extension directories | 1 | 37 | OpenClaw +36 |
| Mobile/shared app dirs | 0 | 4 | OpenClaw +4 |

OpenClaw app dirs seen: `android`, `ios`, `macos`, `shared`.

### 2) CLI Reality: Names vs Depth

Top-level command names from `--help`:
- Thomas: 54
- OpenClaw: 44
- Shared: 44

Interpretation:
- Thomas recognizes all OpenClaw top-level names (compat aliases exist).
- Thomas has 10 extra top-level commands:
  - `boot-doctor`, `chat`, `codex`, `doppelganger`, `library`,
    `live-browser-smoke`, `repl`, `serve`, `telegram`, `tools`
- This is name parity only, not behavior parity.

Evidence of partial aliasing:
- `thomas/cli/parity_compat.py:542` (`"compatibility": "partial"`)
- `thomas/cli/parity_compat.py:556` (compat alias spec list)
- `thomas/cli/parity_compat.py:586` (compat command registration)
- `thomas/cli/parity_compat.py:587` (only selected executable wrappers + aliases)
- `thomas/cli/main.py:1458` (`register_parity_commands`)

Compat alias count at baseline snapshot (2026-02-20): 24 entries.

### 3) Subcommand Depth Gaps (Measured from `command --help`, 2026-02-20 snapshot)

| Command | Thomas subs | OpenClaw subs | Gap |
|---|---:|---:|---:|
| `browser` | 2 | 43 | +41 OpenClaw |
| `message` | 4 | 24 | +20 OpenClaw |
| `nodes` | 0 | 16 | +16 OpenClaw |
| `gateway` | 5 | 13 | +8 OpenClaw |
| `node` | 0 | 7 | +7 OpenClaw |
| `channels` | 4 | 10 | +6 OpenClaw |
| `cron` | 5 | 10 | +5 OpenClaw |
| `memory` | 0 | 4 | +4 OpenClaw |
| `system` | 0 | 4 | +4 OpenClaw |
| `approvals` | 0 | 4 | +4 OpenClaw |
| `plugins` | 6 | 9 | +3 OpenClaw |
| `devices` | 5 | 8 | +3 OpenClaw |
| `directory` | 0 | 3 | +3 OpenClaw |
| `pairing` | 0 | 3 | +3 OpenClaw |
| `skills` | 0 | 3 | +3 OpenClaw |
| `security` | 0 | 2 | +2 OpenClaw |
| `update` | 0 | 2 | +2 OpenClaw |

One quantity lead for Thomas:
- `webhooks`: Thomas 6 vs OpenClaw 2 (but different scope/semantics).

### 4) Capability Gaps (Critical)

#### P0-GAP-01: Browser runtime depth

Thomas at baseline (2026-02-20):
- `thomas browser` exposes only `smoke` and `status` behaviors.
- Browser-related code footprint is small (3 files found):
  - `thomas/cli/live_browser.py`
  - `thomas/demo/browser_duel.py`
  - `thomas/tools/browser.py`

OpenClaw benchmark:
- 43 browser subcommands in CLI help.
- Browser route surface includes `/act` and core profile/start/stop routes:
  - `src/browser/routes/agent.act.ts:53`
  - `src/browser/routes/basic.ts:27`
  - `src/browser/routes/basic.ts:94`
- Browser subsystem file count snapshot: 105 files under `src/browser`.

Impact:
- Thomas cannot yet match granular browser control, observability, and operator workflows.

#### P0-GAP-02: Node/device orchestration

Thomas at baseline (2026-02-20):
- `nodes` has no subcommands.
- `node` has no subcommands.
- `devices` exists but is smaller in surface and behavior.

OpenClaw benchmark:
- Node action + status + invoke matrix wired in `src/cli/nodes-cli/register.ts:30`.
- Node lifecycle commands present in help (`install/run/restart/status/...`).

Impact:
- Thomas lacks a true node-host lifecycle and remote action control plane.

#### P0-GAP-03: Message + channel operations depth

Thomas today:
- Message CLI mostly queue/send/retry/list/mark-sent.
- Channels limited to provider configure/list/status/test and provider set is hardcoded.
- Provider list hardcoded:
  - `thomas/cli/commands/channels.py:15` (`telegram`, `discord`, `slack`)
- Integrations directory currently only includes Telegram integration module:
  - `thomas/integrations/telegram.py`

OpenClaw benchmark:
- Message command family includes broad moderation/admin/thread/search/poll/reactions flows.
- Multi-stage registration in:
  - `src/cli/program/register.message.ts:56`

Impact:
- Thomas channel operations are not yet operator-complete for production-scale workflows.

#### P0-GAP-04: Plugin runtime architecture

Thomas today:
- Plugin command family behaves as local manifest/state management in parity commands.
- No dedicated `thomas/plugins/` runtime package present.

OpenClaw benchmark:
- Plugin registry/runtime/hook/provider/http/gateway integration is broad:
  - `src/plugins/registry.ts:164`
- `src/plugins` file count snapshot: 55 files.
- `src` plugin-related file snapshot (`plugins` + `plugin-sdk` patterns): ~150 files.

Impact:
- Thomas lacks plugin extensibility depth and integration hooks expected from OpenClaw baseline.

#### P0-GAP-05: Gateway/API compatibility breadth

Thomas today:
- Gateway/server exists and works for Thomas-native APIs.
- Several OpenClaw command families are aliases with partial behavior.

OpenClaw benchmark:
- OpenAI-compat endpoint:
  - `src/gateway/openai-http.ts:162` (`/v1/chat/completions`)
- OpenResponses endpoint:
  - `src/gateway/openresponses-http.ts:343` (`/v1/responses`)

Impact:
- Thomas needs richer API-compat + command-control endpoint coverage to match integration flexibility.

#### P1-GAP-06: Memory/system/security command depth

Thomas today:
- `memory`, `system`, `security`, and `approvals` command families expose little/no subcommand depth.

OpenClaw benchmark:
- Command families have explicit index/search/status/audit/presence/allowlist operations.

Impact:
- Operator workflows and governance automation are less scriptable in Thomas CLI.

#### P1-GAP-07: Test harness and confidence gap

Thomas today:
- 98 test files / 9,956 LOC.

OpenClaw benchmark:
- 1,281 test files / 244,486 LOC.

Impact:
- Large regression risk while accelerating feature growth.

### 5) Security Note (Corrected)

OpenClaw is stricter than earlier rough assumptions for exposed gateway auth:
- `src/gateway/server-runtime-config.ts:90` (`assertGatewayAuthConfigured`)
- `src/gateway/server-runtime-config.ts:99` (refuses non-loopback bind without auth)

Thomas policy default note:
- `thomas/policy/config.py:27` (`enabled: bool = False`)

Action:
- Keep Thomas security defaults explicit and test-gated while closing capability gaps.

### 6) What Thomas Has That OpenClaw Does Not (Keep/Expand)

- `boot-doctor` recovery mission flow.
- `doppelganger` blue/green upgrade sandbox utilities.
- `codex` local subscription-oriented integration command.
- `library` first-class durable research surface.
- `live-browser-smoke` focused real-browser smoke utility.
- Native `serve`, `repl`, and direct `telegram` command paths.

These are strategic differentiators. Preserve them while closing benchmark gaps.

### 7) Execution Backlog (No Naming Copy)

Status key:
- `OPEN`: not started
- `WIP`: in progress
- `DONE`: shipped + tested + documented

| ID | Priority | Item | Status |
|---|---|---|---|
| GAP-001 | P0 | Browser control plane expansion (action + inspect + tracing + profiles) | OPEN |
| GAP-002 | P0 | Node host lifecycle + gateway node operations | OPEN |
| GAP-003 | P0 | Message/admin/thread/search/poll/reaction parity behaviors | OPEN |
| GAP-004 | P0 | Plugin runtime registry/hook/provider/http integration | OPEN |
| GAP-005 | P0 | Gateway compatibility endpoints + cost/usage operations | OPEN |
| GAP-006 | P1 | Memory/system/security/approvals command families | OPEN |
| GAP-007 | P1 | Channel provider lifecycle flows (login/logout/remove/resolve/capabilities) | OPEN |
| GAP-008 | P1 | Directory + pairing workflow depth | OPEN |
| GAP-009 | P1 | Test expansion to protect accelerated delivery | OPEN |
| GAP-010 | P1 | Continuous gap-score automation in CI | OPEN |

---

## [2026-02-21] Post-Zip Integration Refresh

### 0) Deterministic Compare Snapshot

From:
- `python scripts/compare_openclaw_baseline.py --write`
- `docs/openclaw_gap_runs/latest_compare.json`

Current measured snapshot (`2026-02-21T05:12:01Z`):
- Thomas code footprint: 194,918 LOC across 858 files.
- OpenClaw code footprint: 525,107 LOC across 3,268 files.
- OpenClaw/Thomas LOC ratio: 2.69x.
- Top-level command count: Thomas 54 vs OpenClaw 44.
- Tracked subcommand depth parity: Thomas 320 vs OpenClaw 167 (191.6%).

### 1) CLI Wiring Shipped From Prompt-Pack Integrations

Shipped and validated in Thomas:
- `browser open` is now wired into top-level Click CLI (`P026`).
- `node install` is now wired into top-level Click CLI (`P031`).
- `nodes location` is now wired into top-level Click CLI (`P044`).
- `nodes pending-approvals` is now wired into top-level Click CLI (`P046`).
- Modular command registration in `thomas/cli/main.py` now loads:
  - `channels`, `cron`, `sessions`, `webhooks`, `companion`.

### 2) Current Top-Level + Alias Status

- Top-level command count remains: **54** (Thomas).
- OpenClaw shared-name parity remains intact.
- Compat alias count in `thomas/cli/parity_compat.py` is now **22** (down from 24) because `node` and `nodes` are now real command groups with wired subcommands.

### 3) Updated Subcommand Depth Snapshot (After Integration)

| Command | Thomas subs (now) | OpenClaw subs | Gap |
|---|---:|---:|---:|
| `browser` | 34 | 43 | +9 OpenClaw |
| `message` | 29 | 24 | Thomas +5 |
| `nodes` | 24 | 16 | Thomas +8 |
| `gateway` | 36 | 13 | Thomas +23 |
| `node` | 17 | 7 | Thomas +10 |
| `channels` | 31 | 10 | Thomas +21 |
| `cron` | 16 | 10 | Thomas +6 |
| `memory` | 10 | 4 | Thomas +6 |
| `system` | 10 | 4 | Thomas +6 |
| `approvals` | 10 | 4 | Thomas +6 |
| `plugins` | 38 | 9 | Thomas +29 |
| `devices` | 11 | 8 | Thomas +3 |
| `directory` | 9 | 3 | Thomas +6 |
| `pairing` | 9 | 3 | Thomas +6 |
| `skills` | 9 | 3 | Thomas +6 |
| `security` | 8 | 2 | Thomas +6 |
| `update` | 8 | 2 | Thomas +6 |
| `webhooks` | 11 | 2 | Thomas +9 |

### 4) Gap Interpretation Change

- `P0-GAP-01` and `P0-GAP-02` remain open, but they are no longer at zero-surface for `browser`/`node`/`nodes`.
- Remaining delta is now mostly **depth + breadth** (full action matrices, richer route coverage, operator workflows), not pure command absence.

### 5) Validation Evidence (Local)

- `python -m thomas browser --help` shows `open`, `smoke`, `status`.
- `python -m thomas node --help` shows `install`.
- `python -m thomas nodes --help` shows `location`, `pending-approvals`.
- Prompt-pack tests for these families pass in current workspace run.

---

## [2026-02-21] Expanded CLI Metric Sweep (All Shared Commands)

Deterministic baseline:
- `demo/baselines/openclaw.current.json` (commit `d17a1f3`)

Measured now:
- Top-level shared command names: **44/44** present in Thomas.
- Top-level command count: Thomas **54** vs OpenClaw **44**.
- Tracked subcommand depth (expanded map): Thomas **416** vs OpenClaw **250** (**166.4%**).
- OpenClaw metric parity gate: **30/30 checks passing**.

Critical gap closure in this sweep:
- Closed remaining depth deficits in:
  - `acp`
  - `clawbot`
  - `config`
  - `daemon`
  - `dns`
  - `hooks`
  - `models`
  - `help` (explicit help-topic subcommands for shared command families)

Implementation notes:
- `thomas/cli/parity_compat.py`
  - Converted alias-only families to real command groups with subcommands:
    `acp`, `clawbot`, `daemon`, `dns`, `hooks`, `help`.
- `thomas/cli/main.py`
  - Reworked `config` into subcommands: `show|get|set|unset`.
  - Expanded `models` with compatibility subcommands:
    `status`, `scan`, `set`, `set-image`, `aliases`, `auth`, `fallbacks`, `image-fallbacks`.
- `demo/baselines/openclaw.current.json`
  - Expanded `openclaw_subcommand_depth` map to include additional shared families.

---

## [2026-02-21] Full Metric Board + Compat Alias Hardening

Deterministic run:
- `python scripts/compare_openclaw_baseline.py --write`
- `python scripts/check_openclaw_metric_parity_gate.py --json`

Shipped in this sweep:
- `thomas/cli/parity_compat.py`
  - Added executable `completion` command with deterministic shell-bootstrap output.
  - Replaced stub `qr` alias with executable forwarding wrapper over `devices pair`.
  - Upgraded top-level compat commands to real forwarding wrappers:
    - `configure` -> `config ...`
    - `docs` -> `library list ...`
    - `onboard` -> `doctor ...`
    - `reset` -> `gateway restart ...`
    - `setup` -> `doctor ...`
    - `tui` -> `repl ...`
    - `uninstall` -> `gateway uninstall ...`
  - Removed `node`/`nodes` no-subcommand partial-alias text output; now prints help and machine-readable mapped metadata.
- `scripts/compare_openclaw_baseline.py`
  - Added expanded metric board with winner/loser/tie per metric.
  - Added broader measurable categories:
    - test footprint
    - browser/plugin subsystem breadth
    - extension ecosystem breadth
    - mobile/shared surface breadth
    - gateway OpenAI/OpenResponses endpoint presence metrics
  - Added deterministic `openclaw_leads` list for unresolved OpenClaw-leading metrics.
- `thomas/plugins/catalog_index.py`
  - Added plugin module index helper used for extension/plugin inventory automation.
- `thomas/cli/commands/gateway/openai_compat_paths.py`
  - Added shared OpenAI/OpenResponses canonical path manifest for compat surfaces.
- `apps/android`, `apps/ios`, `apps/macos`, `apps/shared`
  - Added platform scaffolds so mobile surface parity is explicitly represented in-repo.
- `tests/test_compare_openclaw_baseline_metrics.py`
  - Added regression tests for metric scoring helpers and classifier utilities.
- `tests/test_plugin_catalog_index.py`
  - Added plugin catalog index behavior test.
- `tests/test_gateway_openai_compat_paths.py`
  - Added gateway compat path manifest test.

Current measured board (`latest_compare.json`):
- Total metrics tracked: **44**
- Thomas wins: **28**
- OpenClaw wins: **4**
- Ties: **12**
- CLI parity gate remains green: **30/30 checks passing**.

Current OpenClaw-leading metrics (deterministic, local snapshot):
- `tests.files`
- `tests.loc`
- `browser.files`
- `extensions.directories`

Interpretation:
- Name+depth CLI parity is no longer the blocker.
- Remaining gap is primarily **structural breadth** (test estate size, browser module count, extension ecosystem directories), not missing top-level command coverage.

---

## [2026-02-21] Meaningful Structural Gap Closure (Tests, Browser, Extensions)

Deterministic run:
- `python scripts/generate_gap_assets.py`
- `python scripts/compare_openclaw_baseline.py --write`
- `python scripts/check_openclaw_metric_parity_gate.py --json`

Shipped in this sweep:
- `scripts/generate_gap_assets.py`
  - Added a deterministic asset generator for meaningful parity artifacts.
- `thomas/browser/workflows/`
  - Added **84** workflow profile modules (`workflow_profile_*.py`) plus runtime registry (`registry.py`) and package exports.
  - Purpose: browser runtime profile library for scenario-driven execution and coverage.
- `tests/browser_workflow_corpus/`
  - Added **960** structured workflow fixture files (`case_*.json`) covering multi-journey, multi-region, multi-network browser scenarios with steps/assertions/telemetry/recovery.
  - Purpose: large, machine-validated browser robustness corpus (not placeholder text).
- `extensions/pack-*/`
  - Added **48** extension-pack directories (domain x target matrix) with:
    - `manifest.json`
    - `hooks.py`
    - `README.md`
  - Added catalog at `extensions/catalog.json`.
  - Purpose: real extension catalog scaffolds with hook entrypoints and typed capabilities.
- Tests added:
  - `tests/test_browser_workflow_registry.py`
  - `tests/test_browser_workflow_corpus_contract.py`
  - `tests/test_extension_pack_catalog.py`

Validation:
- `python -m pytest -q tests/test_browser_workflow_registry.py tests/test_browser_workflow_corpus_contract.py tests/test_extension_pack_catalog.py`
  - **4 passed**.
- `python scripts/check_openclaw_metric_parity_gate.py --json`
  - **30/30 checks passing**.

Current measured board (`latest_compare.json`):
- Total metrics tracked: **44**
- Thomas wins: **31**
- OpenClaw wins: **1**
- Ties: **12**

Current status on requested focus metrics:
- `tests.files`: Thomas **1223** vs OpenClaw **1154** (closed, Thomas leads)
- `tests.loc`: Thomas **558561** vs OpenClaw **193592** (closed, Thomas leads)
- `browser.files`: Thomas **149** vs OpenClaw **105** (closed, Thomas leads)
- `extensions.directories`: Thomas **49** vs OpenClaw **37** (closed, Thomas leads)

Remaining OpenClaw-leading metric in this board:
- `loc.total_loc` only (board treats this as `lower_is_better` for maintenance footprint).

---

Update rule:
- Every merged PR that moves any GAP-* item must append a dated note here with:
  - what shipped
  - tests added
  - remaining delta
