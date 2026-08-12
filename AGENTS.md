# Thomas Agent Instructions

## STOP — Read This Before Anything Else

1. Run the startup router: `python scripts/crew/brief/startup_router.py --summary "<task summary>"`
2. Read [GUARDRAILS.md](GUARDRAILS.md) and the module-level `GUARDRAILS.md` for whatever directory you are modifying
3. Read [docs/AGENT_FILE_EDITING_RULES.md](docs/AGENT_FILE_EDITING_RULES.md) — this project has a monolith source loader; editing the wrong file means your changes DO NOTHING
4. Check `agent_safety.toml` for protected files, forbidden patterns, and circular import rules
5. NEVER create split/part files in ANY language — `*_partNN.*`, `*.partNN.*`, `part-NNN.*`, or files inside `*_parts/` directories. This applies to Python, JS, CSS, HTML, and all other languages.
6. NEVER use `exec()` to load code from other files — use normal Python imports
7. NEVER commit with `--no-verify` — pre-commit hooks exist for a reason
8. NEVER modify protected files listed in `agent_safety.toml` without explicit user approval
9. NEVER grow a single file by more than 300 lines in one commit — split across files or commits
10. NEVER stage more than 50 files in one commit — no "snapshot", "checkpoint", or "dump" commits
11. Tag every commit with your model name (e.g., `Thomas-Agent: codex` or `Thomas-Agent: claude`)
12. Run `ruff check` on any Python file you modify before committing

## Agent Coordination Lane (Required)

Thomas is multi-agent. Any agent in this repo MUST run `python scripts/crew/workboard/message.py --list` at session start.

Claude is the coordinator and leader of repo-quality work for Thomas. Codex and any spawned workers report to Claude. Calvin overrides anyone.

Use `scripts/crew/workboard/message.py` for the coordination lane:

- `--send`: create a message.
- `--ack`: acknowledge or decide on a message.
- `--resolve`: mark a message resolved.
- `--list`: read current messages.

Valid message kinds are `blocker`, `brainstorm_call`, `brainstorm_decision`, `brainstorm_note`, `coordination`, `decision`, `handoff`, `ping`, `scope_change`, and `status`.

Valid decisions are `approved`, `none`, `pending`, and `rejected`.

Valid states are `open`, `acked`, and `resolved`.

Workers do one unit at a time, then message Claude with `state=open` and STOP. Workers do not start the next unit until Claude uses `--ack` with `decision=approved`. Approved means proceed. Rejected means correct the requested issue. Use `kind=ping` for questions and wait.

Message Claude after every commit, blocker, decision, surprise, question, and handoff. The default is message and wait, not act and hope.

If Claude needs help, Claude can spawn additional workers and assign them units through the same protocol.

See [docs/AGENT_COORDINATION.md](docs/AGENT_COORDINATION.md) for the full protocol.

## Workbench Operator Protocol

Workbench behavior is documented in `docs/WORKBENCH_OPERATOR_PROTOCOL.md`.

Contract phrase: tabs are AI-first operator control surfaces.

## Rule: UI Code — Delete Old Before Adding New (CRITICAL)

**When you create new UI rendering code, you MUST remove or disable the old version it replaces.**

This is the #1 recurring agent mistake. Agents create new UI code on top of old code, both versions stay live, and the user sees wrong or broken displays. This has happened with:
- Token Economy widget (truncated old version vs. new version)
- Settings panel (old HTML alongside new HTML)
- Module rendering paths (conflicting mount/unmount exports)

**Before writing any new UI code:**
1. `grep -rn "<feature_name>" thomas/server/web/js/` to find all existing versions
2. If an old version exists: FIX IT IN-PLACE or REPLACE IT. Do not create a parallel copy.
3. If you create a new file: DELETE or DISABLE the old rendering path in the SAME commit.
4. After your change: `grep` again to confirm no duplicate exports, mount functions, or template fragments remain.

**You may NOT:**
- Create `feature_v2.js` alongside `feature.js`
- Leave old `window.__moduleName` exports live after moving logic to a new file
- Add new HTML template blocks without removing the old ones they replace
- Assume the old code is dead — verify it's not loaded before ignoring it

**If you're unsure which version is live:** check `index.html` for direct `<script>` tags, and `app_runtime_loader.js` for the split runtime manifest. Those are the ONLY two JS entry points.

## What Thomas Is — Do Not Misjudge This Repo

Thomas is an AI-first workspace platform with a **marketplace of domain modules**. The repo is intentionally broad in scope — that is a feature, not a problem. Everything under `thomas/` that is NOT listed in the Architecture section below is marketplace inventory. Do not refactor, delete, rename, or judge the project based on these modules. They are plugin content for the Thomas marketplace. See `thomas/marketplace/MANIFEST.json` for the full registry.

**Core runtime modules** (the only directories you should modify for core work):

- `thomas/agent/` — Chat dispatch and agent loop
- `thomas/core/` — Config, persistence, token economy, LLM clients (intended bottom tier; do NOT add new imports from server/tools — a few legacy ones remain, tracked as debt in `thomas/_architecture.py`)
- `thomas/server/` — aiohttp web app, routes, web UI
- `thomas/cli/` — CLI and REPL
- `thomas/tools/` — Tool definitions and registry
- `thomas/memory/` — Conversation and context stores
- `thomas/browser/` — Browser automation

**Everything else under `thomas/`** — Marketplace domain modules. Leave them alone unless the user explicitly asks you to work on them.

## Branch awareness (required — prevents duplicate work)

Before creating ANY new file or feature, check for existing work on other branches:

```bash
git branch -a --list '*<keyword>*'          # branches named after the feature
git log --all --oneline --grep='<keyword>'  # commits mentioning it anywhere
```

Replace `<keyword>` with the core noun of your task (e.g., `channel`, `discord`, `voice`, `marketplace`).

**If you find matching branches or commits:**
1. Read the diff: `git log --oneline dev..<branch>` to see what was done (substitute the canonical branch name your session is running against — usually `dev` privately or `main` publicly).
2. Ask the user before building anything new — the work may just need a merge.
3. If the branch has real, working code, merge or cherry-pick it instead of rewriting.

**Why this exists:** Multiple agents (Codex, Claude, Gemini) work on this repo in separate sessions. Agent A may build a feature on a branch and not merge it. Agent B starts a new session, sees no files in the working tree, and rebuilds from scratch — wasting hours and losing Agent A's work. This rule prevents that.

## Branch model (canonical — 2026-05-22)

The active model is:

- `main` — public canonical branch on `origin` (https://github.com/Calvin-Corbett/thomas)
- `dev` — private development branch on `dev-origin` (https://github.com/Calvin-Corbett/thomas-dev). This is where agents live day-to-day.
- `publish-clean`, `release/*` — release-prep / sanitized branches kept as needed but not the daily work surface.
- Older `master` references in legacy docs/commits are historical; the canonical names are `main` (public) and `dev` (private).

## Worktree discipline (required)

- Use only the explicitly assigned worktree path for the task. The session-issued path comes from your agent runtime — do not hardcode an operator's local user path here.
- Do not edit multiple worktrees in one task unless explicitly requested.
- Do not create, remove, move, or rebind worktrees without explicit user approval.
- If branch/worktree intent is unclear, stop and ask before editing.
- If `git status --porcelain` is not clean, do not start normal implementation work in that repo. Clean it first, or use only an explicit audited dirty-worktree override for cleanup/remediation lanes.

## Guardrails — Read Before Writing Code

Before writing ANY code, read:

1. **[docs/AGENT_FILE_EDITING_RULES.md](docs/AGENT_FILE_EDITING_RULES.md)** — Which files actually run in production
2. **[GUARDRAILS.md](GUARDRAILS.md)** — Immutable project-wide rules
3. The `GUARDRAILS.md` in the specific module directory you're modifying

**These rules cannot be bypassed.** If a test fails because of your code, fix your code — not the test. If a file is too large, split it — don't increase the limit. If you're unsure, ask the user.

## Start Here

1. Run `python scripts/crew/brief/startup_router.py --summary "<task summary>"`.
2. Read the returned lane card plus `docs/AGENT_FILE_EDITING_RULES.md`, `GUARDRAILS.md`, and any module `GUARDRAILS.md` the router points to.
3. Use these deeper docs only when the lane requires them:
   - `PROJECT_INDEX.md` for runtime boot paths and system wiring
   - `thomas/_architecture.py` for architecture fitness and dependency rules
   - `KNOWN_ISSUES.md` for recurring pitfalls worth reusing instead of rediscovering

**Keep both files updated.** When you change boot paths, add entry points, move key files, or discover a gotcha that cost significant debugging time — update `PROJECT_INDEX.md`. When you add/remove modules or change dependencies — update `_architecture.py`.

## Changelog & Versioning (Dev Agent Responsibility)

**You own the changelog.** This is your development log — update it as you work, not at the end.

1. **When to write entries:** After each logical unit of work (a bug fix, a new feature, a refactor). Don't batch them.
2. **Version bump:** Any behavioral change needs a version bump in **both** `pyproject.toml` and `thomas/__init__.py`. Bump once per session, not once per change.
3. **Format:** Follow Keep a Changelog categories: `### Added`, `### Changed`, `### Fixed`, `### Removed`. Be specific — name the files, endpoints, or behaviors affected.
4. **What counts:** Code changes, new files, config changes, architectural changes, bug fixes. Pure docs-only changes don't need a version bump but still get a changelog entry under `[Unreleased]` if notable.

**The changelog is the project's memory across sessions.** Future agents rely on it to understand what changed and why.

## How To Write About Calvin (Required — applies to every agent)

Commit messages, changelog entries, PR titles and bodies, and release notes are
public and effectively permanent: a merged pull request keeps its commit list on
GitHub forever. Calvin reads these, and has already found himself described in
them without knowing they existed. This repo runs 58 gates over its code and none
of them read the prose wrapped around it — so this is the rule instead.

1. **Second person.** Write "you" and "your". Not "the owner", not "the user", not
   his name in the third person.
2. **Never characterize his ability, background, or knowledge.** No "is not a
   programmer", "non-technical", "cannot read code", "did not understand". Name
   what the software did and what it failed to show him. That is the finding. The
   person is not the finding.
3. **Quote the request, never judge the requester.** His own words about what he
   wanted are the strongest justification a change can carry. Quote those.
4. **Do not infer pronouns.** They have not been stated. If a third-person
   reference is genuinely unavoidable, use they/them.
5. Applies to everything that leaves this machine: issues, published plans, and
   generated docs — not just commits.

## Agent Commit Path (Required for Agents)

- Use `python scripts/crew/brief/commit.py --message "<msg>"` instead of raw `git commit`.
- `commit.py` isolates claimed files in a temporary git index, runs local gates, and leaves unrelated repo dirt untouched.
- For dirty-worktree fallback: `python scripts/crew/brief/commit.py --include <file> --allow-scope-fallback --fallback-reason "<reason>" --message "<msg>"`
- For merge readiness: `python scripts/forge/gates/merge_readiness.py`
- If no commit is created, report the explicit blocker class: `local_gate_failed`, `broken_repo_tool`, `claim_scope_mismatch`, `branch_race`, or `no_claimed_changes`.

## Before You Delete Code

Never bulk-delete. For EVERY file or function you want to remove:

1. `grep -r '<name>' thomas/ tests/ scripts/ --include='*.py'` — find ALL references
2. If anything imports it: don't delete. Refactor or replace instead.
3. If only lazy/conditional imports: stub with safe fallbacks first.
4. After deletion: verify server boots (`python -m thomas serve --port 0`) and tests pass.

---

## Deep Context — Read Only When Your Task Requires It

Most single-agent sessions do NOT need the sections below. The startup router will tell you when you do.

### Website Dev Shortcut (Dev-Only)

If a task mentions website/site/homepage/domain/Spline or the user asks for web changes:

1. Start in `apps/site` immediately.
2. Read `apps/site/README_DEV.md` first for current URLs and workflow.
3. Run website commands from `apps/site` (`npm run dev`, `npm run typecheck`, deploy scripts).
4. Apply skill `ui-precision-guard` at `skills/ui-precision-guard/SKILL.md` for any UI edit.
5. For `thomas/server/web/**` UI files, use the repo-local `skills/ui-precision-guard` workflow.

### Hard Gate: Website Visual Proof (All Agents)

When UI files change in `apps/site/src/app/**` or `apps/site/src/components/**`, you must update verification artifacts and run:

- `python scripts/refresh_site_visual_proof.py`
- `python scripts/forge/gates/site_visual_proof.py`

Enforcement: pre-commit hook `thomas-site-visual-proof-gate`, CI workflow `site-release.yml`.

### Runtime Skills (Model-Agnostic)

Thomas resolves runtime skills at the orchestrator layer before model calls. Selection order: explicit skill mention > pinned skills from `.thomas/cli/skills.json` > relevance-ranked from discovered roots (`<thomas_install_root>/skills`, `~/.thomas/skills`, `<cwd>/.thomas/skills`, `<cwd>/skills`).

### Multi-Agent Handshake Protocol

When multiple agents are active, use a double-handshake before bundling commits. This applies to every agent identity (Codex, Claude, Grok, Thomas, or human contributors).

**Standard first-pass behavior (non-negotiable unless user overrides):**

- Use `crew/brief/bootstrap_claim.py` for orchestration parents.
- Default to `parent` role (callsign `dispatcher`) with auto dispatch.
- Dispatch minimum floor: 2 workers.
- READY workers released before refill.
- Completion handoff expected: release/mark READY then move on.

**Steps:**

1. **Claim scope:** `python scripts/crew/brief/bootstrap_claim.py --agent "<name>" --scope "<path[,path...]>" --task "<short task>" --name "<name>"`
2. **Mark ready:** `python scripts/crew/workboard/claim.py --claim --agent "<name>" --name "<callsign>" --role <role> --parent <parent-id> --scope "<paths>" --task "[READY][HSK-<id>] <summary>"`
3. **Fan out (parents):** `python scripts/crew/workboard/claim.py --dispatch-workers --agent "<parent-name>" --dispatch-release-ready --dispatch-target-workers 2 --task-manager-agent "thomas"`
4. **Report issues:** `python scripts/crew/workboard/issue.py --block --task-id "<id>" --reporter "<agent>" --summary "<blocker>"`
5. **Acknowledge handoff:** `python scripts/append_handoff.py --title "ACK HSK-<id>" --note "<agent> marked READY"`
6. **Integrator bundles** only after READY+ACK.
7. **Release claims:** `python scripts/crew/workboard/claim.py --release --agent "<name>"`

**Guard rails:** Never commit another agent's scope unless `[READY]` + ACK. Never use `--no-verify` except explicit emergency. SKIP requires `THOMAS_SKIP_BREAKGLASS=1` and is audited.

### Task Ecosystem Control Plane

Every agent must follow `docs/ops/TASK_ECOSYSTEM_PROTOCOL.md`.

Core rules: Thomas routes tasks (agents execute), user tasks outrank background tasks, keep board ordered by priority (`[P0][NOW]`, `[P1][NEXT]`, `[P2][LATER]`), all coordination goes through workboard messages, every tracked task needs `PLAN.md` and `PROBLEM.md`.

Key commands: `workboard_task_manager.py --sync-plans --apply`, `workboard_problem_record.py`, `workboard_message.py --send/--ack/--resolve`.

### LOC Counting Protocol

When a user asks for LOC/SLOC counts, count git-tracked files only (`git ls-files -z`), run language-aware analysis, report commit hash + branch, file coverage stats, SLOC buckets (`prod_app`, `tests`, `docs_config_data`), physical line totals, and top languages. Call out when JSON/config/docs dominate and offer a stricter rerun.
