# Thomas Agent Instructions

Thomas is an AI coding agent with intentionally broad scope.
The breadth is a feature â€” don't reduce scope without explicit user request.

## Worktree discipline (required)
- Read `WORKTREE_RULES.md` before making edits.
- Use only the explicitly assigned worktree path for the task.
- If no worktree is specified, use `C:\Users\corbe\Thomas` (`master`).
- Do not edit multiple worktrees in one task unless explicitly requested.
- Do not create, remove, move, or rebind worktrees without explicit user approval.
- Include the active worktree path in status and handoff updates.
- If branch/worktree intent is unclear, stop and ask before editing.
- If git status --porcelain is not clean, do not start normal implementation work in that repo. Clean it first, or use only an explicit audited dirty-worktree override for cleanup/remediation lanes.

## Router-First Startup (required)
- Run `python scripts/agent_startup_router.py --summary "<task summary>" [--path <repo/path>]...` before loading long docs.
- Read the returned lane card in `docs/ai/CHECKLISTS/` and only the docs it points to.
- Workboard awareness is always required; full claim/handoff protocol is required only when the router flags tracked, risky, broad, shared, or multi-agent work.
- Guided mode is the default. Expert mode reduces visible instructions, but it does not disable hard gates.
## CRITICAL â€” File Editing Rules (Read First!)

**[docs/AGENT_FILE_EDITING_RULES.md](docs/AGENT_FILE_EDITING_RULES.md)** â€” MUST READ before editing ANY file.
This project has a monolith source loader pattern. Multiple copies of the same code exist in different locations.
If you edit the wrong file, your changes DO NOTHING. The doc explains exactly which files to edit.

## Guardrails â€” Read Before Doing Anything

Before writing ANY code, read:
1. **[docs/AGENT_FILE_EDITING_RULES.md](docs/AGENT_FILE_EDITING_RULES.md)** â€” Which files actually run in production
2. **[GUARDRAILS.md](GUARDRAILS.md)** â€” Immutable project-wide rules
3. The `GUARDRAILS.md` in the specific module directory you're modifying

**These rules cannot be bypassed.** If a test fails because of your code, fix your code â€” not the test. If a file is too large, split it â€” don't increase the limit. If you're unsure, ask the user.

## Start Here
1. Run `python scripts/agent_startup_router.py --summary "<task summary>" [--path <repo/path>]...`.
2. Read the returned lane card plus `docs/AGENT_FILE_EDITING_RULES.md`, `GUARDRAILS.md`, and any module `GUARDRAILS.md` the router points to.
3. Use these deeper docs only when the lane requires them:
   - `PROJECT_INDEX.md` for runtime boot paths and system wiring
   - `thomas/_architecture.py` for architecture fitness and dependency rules
   - `KNOWN_ISSUES.md` for recurring pitfalls worth reusing instead of rediscovering

**Keep both files updated.** When you change boot paths, add entry points, move key files,
or discover a gotcha that cost significant debugging time â€” update `PROJECT_INDEX.md`.
When you add/remove modules or change dependencies â€” update `_architecture.py`.

## Changelog & Versioning (Dev Agent Responsibility)

**You own the changelog.** This is your development log â€” update it as you work, not at the end.

1. **When to write entries:** After each logical unit of work (a bug fix, a new feature, a
   refactor). Don't batch them. Don't wait for "before commit." Write it while the context
   is fresh.
2. **Version bump:** Any behavioral change (bug fix, new feature, changed behavior) needs a
   version bump in **both** `pyproject.toml` and `thomas/__init__.py`. Bump once per session,
   not once per change.
3. **Format:** Follow Keep a Changelog categories: `### Added`, `### Changed`, `### Fixed`,
   `### Removed`. Be specific â€” name the files, endpoints, or behaviors affected.
4. **What counts:** Code changes, new files, config changes, architectural changes, bug fixes.
   Pure docs-only changes (README, comments) don't need a version bump but still get a
   changelog entry under `[Unreleased]` if notable.

**The changelog is the project's memory across sessions.** Future agents (including you in a
new context window) rely on it to understand what changed and why. Sloppy changelog = lost
context = repeated mistakes.

## Before You Commit
Run `python -m pytest tests/test_architecture.py -x --tb=short -q`.
It checks dependency direction, file sizes, forbidden patterns, extension
isolation, module coverage, test coverage, health annotations, and cycles.

## Before You Delete Code
Never bulk-delete. For EVERY file or function you want to remove:
1. `grep -r '<name>' thomas/ tests/ scripts/ --include='*.py'` â€” find ALL references
2. If anything imports it: don't delete. Refactor or replace instead.
3. If only lazy/conditional imports: stub with safe fallbacks first.
4. After deletion: verify server boots (`python -m thomas serve --port 0`) and tests pass.

## Deep Context (read only when your task touches these areas)
- UI/tabs: `docs/WORKBENCH_OPERATOR_PROTOCOL.md`
- Workbench framing: tabs are AI-first operator control surfaces.
- Risky changes: `definitions/change-classification.md`
- Agent loop internals: `SOUL.md`
- Current priorities: `plans/thomas/WORKBOARD.md`
- Website releases: deploy via CI (`site-release.yml`), not ad-hoc

## Multi-Agent Handshake Protocol (Required)
When multiple agents are active, use a double-handshake before bundling commits.
This applies to every agent identity that touches the repo (Codex, Claude, Grok, Thomas, or human contributors).

### Standard first-pass behavior (baseline)
Default first-pass behavior is non-negotiable unless user explicitly overrides:
- Use `agent_bootstrap_claim.py` for orchestration parents.
- Default to `parent` role for non-orchestrator agents (using callsign `dispatcher`) and auto-run dispatch.
- Dispatch uses a minimum floor of 2 workers by default.
- READY workers are released before refill by default.
- Completion handoff is expected by default: release/mark READY then move on.

1. Claim scope at start:
   - Set explicit id first (PowerShell): `$env:AGENT_ID="<name>"` (or `$env:THOMAS_AGENT_ID="<name>"`)
   - Non-orchestrator agents MUST enter active implementation work by running `agent_bootstrap_claim.py` (not manual claim flows) so parent role and child dispatch are standardized on day one.
   - Optional one-shot bootstrap: `python scripts/agent_bootstrap_claim.py --agent "<name>" --scope "<path[,path...]>" --task "<short task>" --name "<name>"`
- For non-orchestrator agents, bootstrap defaults to `parent` role/callsign `dispatcher` and auto-runs dispatch to a handful of workers by default.
   - Bootstrap fanout is clamped to at least 2 workers unless explicitly overridden with an explicit higher target.
   - Manual `--dispatch-workers` in `scripts/workboard_claim.py` also enforces the same minimum 2-worker floor.
   - Disable auto dispatch with `--no-auto-dispatch` (keeps bootstrap claim only).
- Orchestrator bootstrap intentionally skips auto-dispatch.
   - `python scripts/workboard_claim.py --claim --agent "<name>" --name "<callsign>" --role <solo|parent|worker> --parent <none|parent-id> --scope "<path[,path...]>" --task "[WIP][HSK-<id>] <short task>"`
2. Mark ready when code/tests are complete:
   - `python scripts/workboard_claim.py --claim --agent "<name>" --name "<callsign>" --role <solo|parent|worker> --parent <none|parent-id> --scope "<path[,path...]>" --task "[READY][HSK-<id>] <summary>"`
   - Move on after completion by default; stay on a task only when explicitly told by user or blocked by unresolved dependency.
3. Parent agents should fan out when possible:
   - `python scripts/workboard_claim.py --suggest-delegation --agent "<parent-name>"`
   - One-command dispatch (release READY workers + claim fresh lanes):  
     `python scripts/workboard_claim.py --dispatch-workers --agent "<parent-name>" --dispatch-release-ready --dispatch-target-workers 2 --task-manager-agent "thomas"`
   - Bootstrap dispatch now inherits this behavior by default and requests task handoff when complete.
   - If no lanes are available, dispatch auto-claims a temporary task-creator lease and notifies orchestrator.
   - Temporary task-creator lease is single-owner: only one agent can hold it at a time.
- Orchestrator clears temp lease when backlog is healthy:  
     `python scripts/workboard_claim.py --release-temp-task-creator --agent "thomas" --task-manager-agent "thomas"`
   - Claim at least one suggested worker task when non-overlapping candidates exist.
4. Report execution issues:
   - Add blocked tasks to `## Active Tasks` with `status=blocked`.
   - Add/maintain a matching entry in `## Issues / Blockers` until resolved.
   - If you cannot continue, move task details into `## Up For Grabs`.
   - Use helper commands:
     - `python scripts/workboard_issue.py --block --task-id "<task_id>" --reporter "<agent>" --summary "<blocker summary>"`
     - `python scripts/workboard_issue.py --triage --issue-id "<issue_id>" --owner "<agent|team>"`
     - `python scripts/workboard_issue.py --resolve --issue-id "<issue_id>"`
     - `python scripts/workboard_issue.py --up-for-grabs --task-id "<task_id>" --reported-by "<agent>"`
5. Acknowledge handoff in the log:
   - `python scripts/append_handoff.py --title "ACK HSK-<id>" --note "<agent> marked READY" --note "<integrator> will bundle"`
6. Integrator bundles only after READY+ACK.
7. Release claims after commit/push:
   - `python scripts/workboard_claim.py --release --agent "<name>"`

Optional hard lock for active edits:
- `python scripts/active_folders.py claim --agent "<name>" --path <folder> --ttl 1800 --note "HSK-<id>"`
- `python scripts/active_folders.py release --agent "<name>"`

Guard rails:
- Check active claims: `python scripts/workboard_claim.py --list`
- Validate claims gate: `python scripts/check_workboard_claims.py --require-identity-metadata`
- Validate task-problem coverage gate: `python scripts/check_workboard_task_problems.py`
- Validate changed-file ownership gate: `python scripts/check_workboard_changed_files.py --staged --require-identity-metadata`
- Validate per-agent gate: `python scripts/check_workboard_agent_claim.py --enforce-staged-scope --enforce-parent-throughput --parent-target-workers 2 --parent-min-ready-suggestions 2`
- Validate canonical repo identity gate: `python scripts/check_repo_identity.py`
- Never commit another agent's scope unless they are marked `[READY]` and ACK is logged.
- Never use `git commit --no-verify` except explicit emergency approval from maintainers.
- `SKIP` is breakglass-only. Standard flow is: fix failing hooks, then commit.
- Emergency SKIP requires `THOMAS_SKIP_BREAKGLASS=1`; agent id is auto-resolved and ticket/reason metadata are auto-generated when missing.
- All SKIP usage is audited to `.git/thomas_skip_audit.jsonl` by `python scripts/check_precommit_skip_policy.py`.
- Breakglass is machine-governed with cooldown/quota/scope caps (per-agent cooldown, 24h quota, and hard staged-file limit).
- Runner skip flags (`--skip-gates`, `--skip-tests`) are breakglass-only and auto-generate missing breakglass metadata.
- Failed runner steps must be recorded in the canonical task problem ledger via `python scripts/workboard_problem_record.py`.
- Configure GitHub hard merge guardrails with `python scripts/configure_github_branch_protection.py --apply` or `powershell -ExecutionPolicy Bypass -File scripts/apply_branch_protection.ps1` (see `docs/GITHUB_BRANCH_PROTECTION_SETUP.md`).
- For proof bundles, run `python scripts/evidence_pack.py --name "<run>" --command "<cmd>" [--command "<cmd2>"]` (see `docs/EVIDENCE_PACK_RUNBOOK.md`).

## Task Ecosystem Control Plane (Required)
Every agent must follow `docs/ops/TASK_ECOSYSTEM_PROTOCOL.md`.

Core rules:
1. Thomas routes tasks through `thomas` (`task-manager-agent` remains a compatibility alias); agents execute.
2. User-requested tasks outrank background tasks.
3. Keep the board ordered by priority and urgency (`[P0][NOW]`, `[P1][NEXT]`, `[P2][LATER]`).
4. All agent-to-agent and agent-to-orchestrator coordination requests go through workboard message traffic.
5. Keep alias identity stable (`Codex 1`, `Codex 2`, etc.) and track unique session ids per run.
6. Every tracked task must have both `PLAN.md` and `PROBLEM.md` records generated via task-manager sync.
7. Use only the canonical Thomas clone and remote identity defined by `docs/ops/repo_identity_policy.json`.
8. Orchestration stewardship is automatic in the orchestrator role: if no active stewardship claim exists for the current board/session, claim `thomas` ownership immediately before any board edits, task creation, or task dispatch.

Required commands:
- Sync plans: `python scripts/workboard_task_manager.py --sync-plans --apply`
- Sync plans with explicit roots: `python scripts/workboard_task_manager.py --sync-plans --plan-root "<path>" --problem-root "<path>" --apply`
- Record a failed check in task problem ledger: `python scripts/workboard_problem_record.py --runner auto_checks --step "<label>" --exit-code <code> --command "<cmd>" --task-id "<task_id>"`
- `python scripts/auto_checks.py` and `python scripts/doc.py` auto-record failed steps to task `PROBLEM.md` unless `--no-record-problem-on-fail` is set.
- Sync sessions: `python scripts/workboard_task_manager.py --sync-sessions --apply`
- Sweep inactive: `python scripts/workboard_task_manager.py --sweep-inactive --max-idle-minutes 1 --apply --task-manager-agent "thomas"`
- Message send: `python scripts/workboard_message.py --send --from-agent "<agent>" --to-agent "<agent|thomas>" --summary "<text>" --task-id "<task_id>"`
- Message ack: `python scripts/workboard_message.py --ack --msg-id "<msg_id>" --by "<agent>"`
- Message resolve: `python scripts/workboard_message.py --resolve --msg-id "<msg_id>" --by "<agent>"`
- Preference capture: `python scripts/workboard_task_manager.py --capture-preference --preference-summary "<summary>" --preference-verbatim "<verbatim>"`

## Website Dev Shortcut (Dev-Only)
If a task mentions website/site/homepage/domain/Spline or the user asks for web changes:
1. Start in `apps/site` immediately.
2. Read `apps/site/README_DEV.md` first for current URLs and workflow.
3. Run website commands from `apps/site` (`npm run dev`, `npm run typecheck`, deploy scripts).
4. Apply skill `ui-precision-guard` at `.codex/skills/ui-precision-guard/SKILL.md` for any UI edit.
5. For `thomas/server/web/**` UI files, use the repo-local `.codex/skills/ui-precision-guard` workflow and satisfy its `Common-Practice Logic Mode` checklist before handoff.

## Runtime Skills (Model-Agnostic)
Thomas resolves runtime skills at the orchestrator layer before model calls.
This applies across providers (Codex, Anthropic, OpenAI-compatible), not just Codex.

Selection order is:
1. Explicit skill mention in prompt (`$skill-name`, inline mention, or `skill <name>`)
2. Pinned skills from `.thomas/cli/skills.json`
3. Relevance-ranked skills from discovered roots

Discovery roots:
- `$CODEX_HOME/skills`
- `~/.codex/skills`
- `<memory_root>/.codex/skills`
- `<cwd>/.codex/skills`
- `<cwd>/skills`
- Optional: `THOMAS_SKILLS_EXTRA_DIRS` (`os.pathsep`-separated)

## Hard Gate: Website Visual Proof (All Agents)
This rule applies to Thomas and any external/competing agent editing this repo.

When UI files change in:
- `apps/site/src/app/**`
- `apps/site/src/components/**`

you must update:
- `apps/site/verification/ui-proof.json`
- `apps/site/verification/runtime-report.json`
- `apps/site/verification/screenshots/full-page.png`
- `apps/site/verification/screenshots/footer-focus.png`
- `apps/site/verification/baselines/full-page.png`
- `apps/site/verification/baselines/footer-focus.png`
- `apps/site/verification/diffs/full-page-diff.png`
- `apps/site/verification/diffs/footer-focus-diff.png`

and run:
- `python scripts/refresh_site_visual_proof.py`
- `python scripts/check_site_visual_proof.py`

Enforcement is hard-coded via:
- pre-commit hook `thomas-site-visual-proof-gate`
- CI workflow `.github/workflows/site-release.yml`
- runtime browser verifier `scripts/verify_site_visual_runtime.mjs` (auto screenshots + DOM assertions)
- proof refresh script `scripts/refresh_site_visual_proof.py` (pixel-diff baseline comparisons)

## LOC Counting Protocol (Default)
When a user asks for LOC/SLOC counts, run the full sweep by default.

Required method:
1. Count git-tracked files only (`git ls-files -z`) so local build artifacts do not skew totals.
2. For each tracked file present on disk, run language-aware analysis with UTF-8 fallback.
3. Report commit hash + branch with the results.
4. Report file coverage stats:
   - tracked files
   - present files
   - missing files
   - analyzer state counts (analyzed/unknown/binary/generated/empty)
5. Report SLOC buckets:
   - `prod_app`
   - `tests`
   - `docs_config_data`
   - `total_buckets`
6. Report physical line totals:
   - all present files
   - text files only
   - binary/text file counts
7. Report top languages by SLOC:
   - total repo
   - `prod_app` subset
8. Call out when JSON/config/docs dominate totals, and offer a stricter "pure app code" rerun (exclude JSON/lock/docs/diff) when needed.
