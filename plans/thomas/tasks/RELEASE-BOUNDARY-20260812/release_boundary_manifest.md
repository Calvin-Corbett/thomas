# Release Boundary Classification Manifest

task_id: `RELEASE-BOUNDARY-20260812`  
Phase: 1 (classify) -- **awaiting human approval before Phase 2**

Buckets: **1** = process, repo-only, never ships. **2** = contributor infrastructure, repo-only. **3** = engineering capability worth porting into the product. **P** = product, ships today and should continue to.


## Findings that need a decision before Phase 2

### F1 -- `AGENTS.md` is read by the shipped product at runtime

`thomas/agent/guidance.py:16` loads `AGENTS.md` as the highest-weighted entry in
`_DEFAULT_GUIDANCE_FILES`, alongside `IDENTITY.md`, `USER.md`, `SOUL.md`,
`definitions/autopoietic.md` and `definitions/change-classification.md`. The task brief
classifies `AGENTS.md` as bucket 1, never ships. **I disagree with that assignment as
written, and flag it rather than override it.**

Excluding it is *safe*: `load_purpose_brief` checks `path.exists()` and skips what is
missing, and `README.md` is marked fallback-only precisely so it takes over when dedicated
guidance is absent. Nothing crashes. But it is not *inert* -- the shipped agent purpose
brief loses its top-weighted source, and `guidance_bootstrap_report()` will report
`exists: false`. That is a behavioural change to the product, not only a packaging change.

Three options, owner decision:

1. Ship `AGENTS.md`. Contradicts the brief, and it is full of workboard and claim rules
   that mean nothing to a user.
2. Exclude it and accept the degraded brief. The README fallback already exists for this.
3. Exclude it and split the product-relevant guidance into a shipped file, leaving the
   process rules behind. **Recommended** -- the only option where neither the user nor the
   shipped agent inherits this repo process vocabulary.

### F2 -- `definitions/` is also a runtime guidance source

Same loader, entries 5 and 6 (`autopoietic.md`, `change-classification.md`). Same three
options as F1. Marked UNRESOLVED below.

### F3 -- `SOUL.md` and `IDENTITY.md` are product, not process

Both are runtime guidance sources and describe the Thomas persona, not this repo workflow.
Classified **P**. Worth stating explicitly because they sit beside `AGENTS.md` and
`CLAUDE.md` in the repo root and look like the same kind of file.

### F4 -- bucket 3 is a port, not a copy (confirms the brief)

Measured across all 59 gates: **55 hardcode `parents[3]` or `parents[2]`**, only **16**
accept any target argument, and **20** read this repo own state. Of the 11 named bucket-3
candidates, 7 hardcode the root and several read repo state. The brief assessment is correct.


## Top-level paths

| path | bucket | justification |
|---|---|---|
| `thomas/` | P | The product package itself. |
| `evolve_supervisor/` | P | Already in the wheel include list; runtime supervisor. |
| `skills/` | P | Product skills (gh-fix-ci, cloudflare-deploy); loaded by thomas/cli/repl_runtime.py. |
| `extensions/` | P | Plugin surfaces read by thomas/server/desktop_plugins_manifest.py at runtime. |
| `installer/` | P | Cold-install path. |
| `assets/` | P | Application icons. |
| `web/` | UNRESOLVED | Referenced once as a plugin surface path (agent_plugins_adapter.py:186 -> web/about.html). Unclear whether the top-level tree is live or superseded by thomas/server/web/. |
| `ollama/` | P | Local model system prompt shipped with the runtime. |
| `README.md` | P | User-facing entry documentation. |
| `LICENSE` | P | Required in any distribution. |
| `SECURITY.md` | P | User-facing vulnerability reporting policy. |
| `CHANGELOG.md` | P | User-facing release history. |
| `SOUL.md` | P | Runtime guidance source (guidance.py); product persona. See F3. |
| `IDENTITY.md` | P | Runtime guidance source (guidance.py); product persona. See F3. |
| `pyproject.toml` | P | Install metadata. |
| `requirements-lock.txt` | P | Pinned install. |
| `MANIFEST.in` | P | Packaging control. |
| `sitecustomize.py` | P | Runtime import hook. |
| `evolve_governor.toml` | P | Spend caps (daily_usd_cap, total_usd_cap) read at runtime by evolve_supervisor/spend_governor.py, which ships. Excluding it would remove a spend limit from a shipped component -- treat as a hard must-ship. |
| `thomas.toml` | P | Default product config. |
| `thomas.prod.toml` | P | Production product config. |
| `Dockerfile` | P | Supported deployment path. |
| `docker-compose.yml` | P | Supported deployment path. |
| `.env.example` | P | Install-time configuration template. |
| `.env.thomas.production.example` | P | Install-time configuration template. |
| `install.cmd, install.sh, setup.cmd` | P | Cold-install entry scripts. |
| `run-ui.cmd, run-repl.cmd, repair.cmd, bootdoctor.cmd` | P | User-facing launchers. |
| `launch-thomas.vbs` | P | Desktop launcher. |
| `build-installer.cmd` | 2 | Builds the installer; a maintainer action, not a user action. |
| `AGENTS.md` | UNRESOLVED | Brief says bucket 1; the runtime guidance loader reads it. See F1. |
| `definitions/` | UNRESOLVED | Brief implies process; two files are runtime guidance sources. See F2. |
| `CLAUDE.md` | 1 | Instructions to one coding agent about this repo workflow. |
| `CONTRIBUTING_AI.md` | 1 | Contribution process for agents working on this repo. |
| `PROJECT_MANAGEMENT_RULES.md` | 1 | This repo management process. |
| `GUARDRAILS.md` | 1 | Immutable rules for agents developing Thomas. |
| `agent_safety.toml` | 1 | Protected-file and forbidden-pattern config for this repo gates. |
| `plans/` | 1 | Workboard, claims, task problems, session state. |
| `evolve_corpus/` | 1 | Corpus for this repo self-improvement loop. |
| `code_intake/` | 1 | Intake queue for this repo development process. |
| `library/` | 1 | Owner library scaffold; entries are gitignored after the 2026-05-19 leak. Never ship. |
| `demo/` | 1 | Demo and baseline artifacts produced while developing Thomas. |
| `patches/` | 1 | Historical guardrail patches; development archaeology. |
| `tools/` | 1 | One-off apply_* migration scripts for this repo. |
| `docs/` | UNRESOLVED | Mixed: user-facing (DEPLOYMENT, ONBOARDING) and process (docs/ai/*, CHECKLISTS). Needs a per-subdirectory split, not one bucket. |
| `ARCHITECTURE.md` | 2 | Contributor orientation for this codebase. |
| `DEPLOYMENT.md` | P | User-facing deployment instructions. |
| `ONBOARDING.md` | UNRESOLVED | Title suggests user onboarding; content may be contributor onboarding. Not read closely enough to call. |
| `DOCUMENTATION_INDEX.md` | 2 | Index over repo documentation. |
| `tests/` | 2 | Contributor infrastructure; explicitly bucket 2 in the brief. |
| `.github/` | 2 | CI definition; contributor infrastructure. |
| `.pre-commit-config.yaml` | 2 | Local hook wiring for contributors. |
| `.gitignore, .gitattributes, .dockerignore` | 2 | Repository mechanics. |
| `docker-compose.dev.yml` | 2 | Developer compose profile. |
| `apps/` | UNRESOLVED | 145 files across android/ios/macos. Could be shipped client shells or unbuilt scaffolding. Not inspected deeply enough to call. |
| `scripts/` | split | Not a single bucket. See the gate table below, plus scripts/crew (bucket 1) and the packaging/install scripts (P). |

## `scripts/forge/gates/` -- all 59

`repo-state` = reads workboard/claims/plans/worktrees. `hard-root` = hardcodes `parents[3]`. `target` = accepts a repo or path argument today.

| gate | bucket | repo-state | hard-root | target | justification |
|---|---|---|---|---|---|
| `__init__.py` | 2 | - | - | - | Contributor infrastructure: guards this repo CI/release lane, no user value. |
| `_quickbuilder_guard.py` | 2 | - | - | - | Contributor infrastructure: guards this repo CI/release lane, no user value. |
| `_runtime_guard.py` | 2 | - | - | - | Contributor infrastructure: guards this repo CI/release lane, no user value. |
| `boot_smoke_gate.py` | 3 | yes | yes | - | Named bucket-3 candidate; general engineering value on any repo. NOTE: currently reads this repo state -- port required. |
| `bulk_commit_guard.py` | 2 | - | yes | yes | Contributor infrastructure: guards this repo CI/release lane, no user value. |
| `cage_egress_guard.py` | 2 | - | yes | yes | Contributor infrastructure: guards this repo CI/release lane, no user value. |
| `changelog_gate.py` | 3 | yes | yes | - | Named bucket-3 candidate; general engineering value on any repo. NOTE: currently reads this repo state -- port required. |
| `chat_control_protocol.py` | 2 | - | yes | - | Contributor infrastructure: guards this repo CI/release lane, no user value. |
| `circular_imports_gate.py` | 3 | yes | yes | - | Named bucket-3 candidate; general engineering value on any repo. NOTE: currently reads this repo state -- port required. |
| `claim_integrity.py` | 1 | - | yes | yes | Enforces this repo development process by name. |
| `commit_growth_guard.py` | 2 | - | yes | yes | Contributor infrastructure: guards this repo CI/release lane, no user value. |
| `commit_scope_gate.py` | 1 | - | yes | - | Enforces this repo development process by name. |
| `core_overhead_guard.py` | 2 | - | yes | - | Contributor infrastructure: guards this repo CI/release lane, no user value. |
| `deletions.py` | 2 | - | yes | yes | Contributor infrastructure: guards this repo CI/release lane, no user value. |
| `dependency_gate.py` | 3 | - | yes | - | Named bucket-3 candidate; general engineering value on any repo. |
| `duplicate_filename_gate.py` | 3 | yes | yes | - | Named bucket-3 candidate; general engineering value on any repo. NOTE: currently reads this repo state -- port required. |
| `enforcement_integrity.py` | 2 | - | yes | - | Contributor infrastructure: guards this repo CI/release lane, no user value. |
| `exception_handler_gate.py` | 3 | yes | yes | - | Named bucket-3 candidate; general engineering value on any repo. NOTE: currently reads this repo state -- port required. |
| `feature_catalog_gate.py` | 2 | - | yes | - | Contributor infrastructure: guards this repo CI/release lane, no user value. |
| `feature_registry.py` | 2 | - | yes | - | Contributor infrastructure: guards this repo CI/release lane, no user value. |
| `frontend_lint_gate.py` | 3 | - | yes | - | Named bucket-3 candidate; general engineering value on any repo. |
| `merge_readiness.py` | 1 | yes | yes | - | Reads or writes this repo workboard, claims, plans, worktrees or session state. |
| `model_onboarding_gate.py` | 2 | - | yes | - | Contributor infrastructure: guards this repo CI/release lane, no user value. |
| `module_audit_gate.py` | 2 | - | yes | - | Contributor infrastructure: guards this repo CI/release lane, no user value. |
| `monolith_baseline_approval_gate.py` | 2 | - | yes | yes | Contributor infrastructure: guards this repo CI/release lane, no user value. |
| `monolith_filename_guard.py` | 2 | - | yes | yes | Contributor infrastructure: guards this repo CI/release lane, no user value. |
| `monolith_guard.py` | 3 | - | yes | yes | Named bucket-3 candidate; general engineering value on any repo. |
| `mutating_route_policy_exceptions.py` | 2 | - | yes | yes | Contributor infrastructure: guards this repo CI/release lane, no user value. |
| `onboarding_outcomes_gate.py` | 2 | - | yes | - | Contributor infrastructure: guards this repo CI/release lane, no user value. |
| `placeholder_completion_policy.py` | 2 | - | yes | yes | Contributor infrastructure: guards this repo CI/release lane, no user value. |
| `plan_structure_gate.py` | 1 | yes | yes | - | Reads or writes this repo workboard, claims, plans, worktrees or session state. |
| `precommit_skip_policy.py` | 1 | yes | yes | - | Reads or writes this repo workboard, claims, plans, worktrees or session state. |
| `protected_files_gate.py` | 1 | yes | yes | - | Reads or writes this repo workboard, claims, plans, worktrees or session state. |
| `public_repo_leak_guard.py` | 3 | - | yes | - | Named bucket-3 candidate; general engineering value on any repo. |
| `release_hygiene.py` | 2 | - | yes | - | Contributor infrastructure: guards this repo CI/release lane, no user value. |
| `release_lane_policy.py` | 1 | - | - | - | Enforces this repo development process by name. |
| `release_sync_gate.py` | 2 | - | yes | yes | Contributor infrastructure: guards this repo CI/release lane, no user value. |
| `release_update_gate.py` | 2 | - | yes | - | Contributor infrastructure: guards this repo CI/release lane, no user value. |
| `repl_scope.py` | 2 | - | yes | - | Contributor infrastructure: guards this repo CI/release lane, no user value. |
| `repo_hygiene.py` | 1 | yes | yes | yes | Reads or writes this repo workboard, claims, plans, worktrees or session state. |
| `repo_identity.py` | 1 | - | yes | yes | Enforces this repo development process by name. |
| `shrinkage_gate.py` | 2 | - | yes | - | Contributor infrastructure: guards this repo CI/release lane, no user value. |
| `site_visual_proof.py` | 2 | - | yes | yes | Contributor infrastructure: guards this repo CI/release lane, no user value. |
| `surface_parity.py` | 2 | - | yes | - | Contributor infrastructure: guards this repo CI/release lane, no user value. |
| `test_coverage_gate.py` | 3 | yes | yes | - | Named bucket-3 candidate; general engineering value on any repo. NOTE: currently reads this repo state -- port required. |
| `type_safety_gate.py` | 3 | yes | yes | - | Named bucket-3 candidate; general engineering value on any repo. NOTE: currently reads this repo state -- port required. |
| `verification_record_gate.py` | 2 | - | yes | - | Contributor infrastructure: guards this repo CI/release lane, no user value. |
| `workboard_agent_claim.py` | 1 | yes | yes | - | Reads or writes this repo workboard, claims, plans, worktrees or session state. |
| `workboard_changed_files.py` | 1 | yes | yes | - | Reads or writes this repo workboard, claims, plans, worktrees or session state. |
| `workboard_claim_freshness.py` | 1 | yes | yes | - | Reads or writes this repo workboard, claims, plans, worktrees or session state. |
| `workboard_claims.py` | 1 | yes | yes | - | Reads or writes this repo workboard, claims, plans, worktrees or session state. |
| `workboard_inbox.py` | 1 | yes | yes | - | Reads or writes this repo workboard, claims, plans, worktrees or session state. |
| `workboard_inbox_hook.py` | 1 | yes | yes | - | Reads or writes this repo workboard, claims, plans, worktrees or session state. |
| `workboard_task_problems.py` | 1 | yes | yes | - | Reads or writes this repo workboard, claims, plans, worktrees or session state. |
| `worktree_branch_guard.py` | 1 | - | yes | - | Enforces this repo development process by name. |
| `worktree_creation_gate.py` | 1 | yes | yes | yes | Reads or writes this repo workboard, claims, plans, worktrees or session state. |
| `worktree_rules_gate.py` | 1 | - | yes | - | Enforces this repo development process by name. |
| `xfail_growth_gate.py` | 2 | - | yes | - | Contributor infrastructure: guards this repo CI/release lane, no user value. |
| `zz_oldgrowth_probe.py` | 2 | - | yes | yes | Contributor infrastructure: guards this repo CI/release lane, no user value. |

**Gate totals:** bucket 1 = 19, bucket 2 = 29, bucket 3 = 11.


## Phase 2 is blocked pending approval of this manifest

Specifically needed: a decision on F1 and F2 (`AGENTS.md`, `definitions/`), and a call on the remaining UNRESOLVED paths (`web/`, `docs/`, `apps/`, `ONBOARDING.md`). Guessing here either ships internal state or breaks a cold install, which is why the brief made this a human gate.

