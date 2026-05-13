# Thomas

Thomas is an AI workspace that starts simple, then grows into memory, tools, and automation without forcing normal users to learn the whole system on day one.

Fresh install: run `run-ui.cmd`, open `http://127.0.0.1:8899`, and finish Easy Setup.

## Everyday Use

The normal-user contract is simple:

- Chat: ask Thomas questions, plan work, and keep the main surface calm.
- Tasks: turn requests into checklists, follow-ups, and next actions.
- Memory: keep context between sessions only when you want it.
- Integrations: connect providers and tools gradually instead of all at once.
- Repair: use `status`, `quickstart`, `setup`, or `repair.cmd` when something drifts.

## Grow Into Advanced Thomas Safely

The deeper orchestration, workboards, swarms, and builder/operator surfaces are intentional. They exist so Thomas can expand without becoming fragile. Normal use should not require understanding those systems on day one.

## For AI Agents & Contributors

Start with the router, not the long doc chain:

1. **Run** `python scripts/agent_startup_router.py --summary "<task summary>" [--path <repo/path>]...`
2. **Read** the returned lane card and only the docs it points to
3. **Escalate** into the heavier lane only when the router says the task is risky, broad, shared, or multi-agent

Canonical router doc: **[docs/ai/AGENT_ROUTER.md](docs/ai/AGENT_ROUTER.md)**.
Long-form docs remain reference material, not default first-pass reading.

Do NOT start building without checking the Inbox and existing code first. See [PROJECT_MANAGEMENT_RULES.md](PROJECT_MANAGEMENT_RULES.md).

## Product-Release Warning (Important)

This repo is an early product release and is still in active stabilization.
Core behavior is intended to work, but the codebase is fast-built and still has UI polish risk.
Expect transient layout or interaction artifacts (especially in dense composer / overlay screens) and plan for an incremental hardening pass.

---

## Start Here (Fresh Download)

If this is your first time running Thomas on this machine, do this first:

1. Run `run-ui.cmd`
2. Wait for first-launch bootstrap to finish (dependencies + starter profile)
3. Open `http://127.0.0.1:8899` if it does not open automatically
4. Complete Easy Setup. Thomas verifies the connection before it unlocks chat, memory, and automation.

Optional advanced/manual setup: run `setup.cmd`.
If setup breaks, run `repair.cmd` (or use `Auto Repair` in the onboarding wizard).
Installer build docs: `docs/WINDOWS_INSTALLER_GUIDE.md`.
Troubleshooting and model setup details are in `ONBOARDING.md`.
Security policy: `SECURITY.md`.
GitHub publishing safety workflow: `docs/GITHUB_PUBLISH_SAFETY_WORKFLOW.md`.
Gateway security runbook: `docs/ops/GATEWAY_SECURITY_RUNBOOK.md`.
Retry guidance: `docs/ops/RETRY_POLICY.md`.
Docker deploy: `docs/ops/DOCKER_DEPLOY.md`.
Production release checklist: copy `.env.thomas.production.example` -> `.env.thomas.production` (or inline env), then:

1. Set a strong `THOMAS_SERVER_API_TOKEN`.
2. Set `THOMAS_MUTATING_CSRF_TOKEN` if you want request-level protection for all mutating `/api` and `/gateway` routes.
3. Start with `THOMAS_ENV=production`.
4. Verify `/api/health` returns before opening external traffic.
5. Keep logs rotating via `THOMAS_LOG_FILE`, `THOMAS_LOG_MAX_BYTES`, and `THOMAS_LOG_BACKUP_COUNT`.
6. Keep `THOMAS_ALLOW_REMOTE_PRODUCTION=1` only for explicitly approved remote deployments.

## Documentation Index (Authoritative)

- Canonical active-doc index: `PROJECT_INDEX.md`
- Root doc archive map: `docs/ops/ROOT_DOC_ARCHIVE_INDEX.md`
- Active planning board: `plans/thomas/WORKBOARD.md`
- Planning hub: `plans/thomas/README.md`
- Repo structure source of truth: `docs/REPO_STRUCTURE_PROTOCOL.md`
- Task ecosystem protocol: `docs/ops/TASK_ECOSYSTEM_PROTOCOL.md`

## Repo Orientation

For agent coordination and planning:
- `docs/REPO_STRUCTURE_PROTOCOL.md` is the repository organization source of truth.
- `plans/thomas/WORKBOARD.md` is the active execution board.
- `docs/ops/TASK_ECOSYSTEM_PROTOCOL.md` defines the required task-manager, messaging, and session workflow.
- `plans/thomas/README.md` links current Thomas plans.
- Active plans should be created in `plans/thomas/` (`tasks/`, `problems/`, and canonical plan files), not randomly in `docs/` or repo root.
- Enforced checks: `scripts/forge/gates/plan_structure_gate.py` and `scripts/check_release_update_gate.py`.
- Local auto-enforcement available via `.pre-commit-config.yaml`.

Required ecosystem commands:
- `python scripts/workboard_task_manager.py --sync-plans --apply`
- `python scripts/workboard_task_manager.py --sync-sessions --apply`
- `python scripts/workboard_task_manager.py --sync-specialists --apply`
- `python scripts/workboard_task_manager.py --specialist-for-task --task-id "<task_id>"`
- `python scripts/workboard_task_manager.py --monitor --apply --cycles 0 --interval-seconds 30 --task-manager-agent "task-manager-agent"`
- `python scripts/workboard_message.py --send --from-agent "<agent>" --to-agent "<agent|task-manager-agent>" --summary "<text>" --task-id "<task_id>"`
- `python scripts/workboard_worker.py --agent "Codex 2" --cycles 0 --poll-seconds 15 --catalog "plans/thomas/worker_command_catalog.json" --max-completions 0`
- `python scripts/workboard_brainstorm.py --start --task-id "<task_id>" --summary "<brief>" --objective "<outcome>" --facilitator "task-manager-agent" --all-hands`
- `python scripts/workboard_brainstorm.py --contribute --session-id "<session_id>" --agent "<agent>" --kind proposal --summary "<idea>"`
- `python scripts/workboard_brainstorm.py --resolve-session --session-id "<session_id>" --summary "<decision>" --dispatch-item "task_id|scope|summary"`
- `python scripts/workboard_swarm.py --create --task-id "<task_id>" --size 8 --agent-prefix "Codex" --agent-start 1 --spawn-command "codex"`
- `python scripts/workboard_swarm.py --launch --swarm-id "<swarm_id>"`
- `python scripts/workboard_swarm.py --status --swarm-id "<swarm_id>"`

## Companion App Scope (Read Before Building Companion)

Thomas companion is now scoped as an immutable-kernel + module platform.

Source of truth:
- `docs/COMPANION_PLATFORM_SCOPE.md`
- `docs/COMPANION_APP_INTEGRATION.md`
- `docs/COMPANION_BUILDER_RELEASE_GUIDE.md`
- `plans/thomas/companion/STORE_COMPLIANCE_PLAN.md`

Minimum requirements (frozen for v0 handoff):
1. Immutable host kernel boundary (modules cannot overwrite kernel paths).
2. Versioned module contract (id/version/entrypoint/permissions/slots/ui schema).
3. Signed update verification + rollback backups before module replacement.
4. Tailscale-only remote control/update identity (localhost dev allowed).
5. Permission allowlist enforcement for modules.
6. Audit trail for verify/apply/update events and module provenance.

Companion scaffold in repo:
- `thomas/companion/`
- `thomas companion init|status|module-list|verify-bundle|apply-bundle|write-template`
- API scaffold for companion app integration:
  - `GET /api/companion/v1/status`
  - `GET /api/companion/v1/contract`
  - `GET /api/companion/v1/studio/capabilities`
  - `GET /api/companion/v1/policy/profiles`
  - `GET /api/companion/v1/policy/profile/{profile_id}`
  - `POST /api/companion/v1/compliance/check`
  - `GET /api/companion/v1/bootstrap`
  - `GET /api/companion/v1/modules`
  - `GET /api/companion/v1/slots`
  - `GET /api/companion/v1/slots/{slot}`
  - `POST /api/companion/v1/modules/{module_id}/enable`
  - `POST /api/companion/v1/modules/{module_id}/disable`
  - `POST /api/companion/v1/studio/build-bundle`
  - `POST /api/companion/v1/bundles/preview`
  - `POST /api/companion/v1/bundles/verify`
  - `POST /api/companion/v1/bundles/apply`
  - `POST /api/companion/v1/ship`
  - `GET /api/companion/v1/devices`
  - `POST /api/companion/v1/devices/register`
  - `POST /api/companion/v1/devices/{device_id}/heartbeat`
  - `POST /api/companion/v1/devices/{device_id}/updates/check`
  - `POST /api/companion/v1/devices/{device_id}/pin-release`
  - `POST /api/companion/v1/devices/{device_id}/unpin-release`
  - `GET /api/companion/v1/releases`
  - `GET /api/companion/v1/releases/{release_id}`
  - `GET /api/companion/v1/releases/{release_id}/manifest`
  - `GET /api/companion/v1/releases/{release_id}/download`
  - `POST /api/companion/v1/releases/publish`
  - `POST /api/companion/v1/releases/{release_id}/rollout`
  - `POST /api/companion/v1/releases/{release_id}/promote`
  - `POST /api/companion/v1/releases/{release_id}/rollback`
  - `GET /api/companion/v1/audit/events`
- Companion Builder screen:
  - `GET /companion`
- App handoff contract doc:
  - `docs/COMPANION_APP_INTEGRATION.md`
- TypeScript SDK for companion app:
  - `thomas/companion/sdk/typescript/`

This zip adds:

- `thomas/core/rag_index.py`
- `thomas/tools/search_code.py`

## Dependencies

Semantic vector search:
```bash
pip install chromadb sentence-transformers
```

Lexical search:
- Uses SQLite FTS5 (built into many Python sqlite builds)
- If FTS5 isn't available, lexical search auto-disables.

## Whatâ€™s meaningfully better (why users will love it)

### Hybrid search (semantic + lexical)
- Semantic search finds â€œmeaningâ€
- Lexical search finds exact identifiers/strings
- Results are fused via Reciprocal Rank Fusion (RRF) for best-of-both.

### Query operators (inside the query string)
No schema changes. Just write:
- `path:thomas/tools ToolRegistry`
- `file:rag_index.py build`
- `ext:.py registry register`
- `symbol:ToolRegistry kind:class`
- `phrase:"ToolRegistry class"`
- `regex:/rag\.search/`

### Line-numbered previews
search() returns snippets formatted with line numbers when it can read the file from disk,
so results are immediately actionable.

### Smarter chunking
- Python: AST blocks (functions/classes) with symbol metadata
- Markdown: heading blocks
- Fallback: 400-token overlap chunks

### Safe indexing
- One background worker thread
- Debounced updates
- Incremental builds + deleted file pruning

## Usage

### Build (non-blocking)
```python
from thomas.core.rag_index import get_rag_index
get_rag_index().build(r"<repo_root>")
```

### Update after file write (non-blocking)
```python
from thomas.core.rag_index import get_rag_index
get_rag_index().update(path_to_written_file)
```

### Tool
```python
from thomas.tools.search_code import TOOL
registry.register(TOOL)
```

Example calls:
```json
{"tool":"rag.search","args":{"query":"path:thomas/tools ToolRegistry register", "k":5}}
```

```json
{"tool":"rag.search","args":{"query":"regex:/rag\\.search/", "k":5}}
```

## Doc Reliability Runner

Run the "Doc" quality sweep (gates + critical protocol tests):

```bash
python scripts/doc.py
```

Run with a full repository pytest pass after quick checks:

```bash
python scripts/doc.py --full
```

## Auto Checks

Run one command for syntax/lint + gates + the step-up test protocol:

```bash
python scripts/auto_checks.py
```

Run the repo-wide pytest ladder directly:

```bash
python scripts/test_stepup_protocol.py
```

Add the final monolithic suite only after those stages are green:

```bash
python scripts/test_stepup_protocol.py --max-stage full
```

Run only fast static checks locally:

```bash
python scripts/auto_checks.py --quick
```

Clean junk artifacts and report worktree cleanliness:

```bash
thomas repo-clean --apply --strict
```

## GitHub User Release Bundle

Use this command to build a deployable product release bundle for GitHub from the current checkout:

```bash
python scripts/package_release.py --version 0.14.30
```

For default safety the release excludes untracked files, plans, tasks, and runtime artifacts.
Use `--include-untracked` only for intentional local-only snapshots.

Output:
- `dist/github-release/thomas-user-release-<version>/` (staged source)
- `dist/github-release/thomas-user-release-<version>.zip` (default archive)

The generated bundle:
- Excludes plans/tasks/conversations/runtime/state artifacts and local secrets.
- Includes a generated `THIRD_PARTY_NOTICES.md`.
- Includes `LICENSE` and release metadata (`RELEASE_SUMMARY.md`, `RELEASE_MANIFEST.json`) so users can audit included files.

Quick gate-ready status check:

```bash
thomas status --json --strict-worktree
```

Install local git hooks (commit + push guards):

```bash
pre-commit install
pre-commit install --hook-type pre-push
```
## Rules Of The Road Quality Gate

Thomas now enforces per-job completion checks before finalizing tasks:

- `coding`, `config`, `planning`, `research`, `video_design`, `general`
- attaches a rules report in run output: `token_report.rules_of_road`
- when `[quality].enforce = true`, Thomas auto-retries failed required checks
  up to `[quality].max_auto_retries`

See `docs/RULES_OF_THE_ROAD_PROTOCOL.md`.
