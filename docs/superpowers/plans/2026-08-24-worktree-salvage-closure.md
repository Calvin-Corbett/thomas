# Worktree Salvage & Closure Implementation Plan (spec phase 0.3 completion)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Reduce 67 worktrees to a handful, losing provably nothing: archive every worktree's unique commits AND dirty state into refs before removal, with a working restore command.

**Architecture:** A salvage tool creates two archive refs per worktree (`refs/archive/worktree/<name>` at HEAD; `refs/archive/worktree/<name>-dirty` holding a snapshot commit of tracked changes + untracked non-ignored files, built via a temp GIT_INDEX_FILE so the worktree's real index is never touched). Removal is refused unless both refs verify. A restore subcommand round-trips. Live execution runs in three batches (ordinary → junction-carrying → %TEMP% monsters) with the Task-1 triage tool re-run between batches.

**Tech Stack:** Python 3.12, pytest, git plumbing (add -A with GIT_INDEX_FILE, write-tree, commit-tree, update-ref). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-24-praxis-first-design.md` (phase 0.3: "Triage: salvage-list per worktree, land or archive, remove.") Owner delegation 2026-08-24: engineering decisions are the controller's; salvage-first converts removal from destructive to reversible.

## Global Constraints

Same as `docs/superpowers/plans/2026-08-24-phase0-and-watcher-of-watchers.md` Global Constraints (wrapper commits, no double quotes in messages, park dirty CHANGELOG, ruff, sentence-named tests, <800-line files, no `*_part*.py`/`exec()`), plus:
- **The venv-junction rule is load-bearing here:** if `<wt>/.venv` is a junction, remove the LINK ONLY (`os.rmdir` on the junction path deletes the reparse point, never the target) BEFORE `git worktree remove`. Assert the junction target (the main `.venv`) still exists afterward.
- **Never remove the main checkout.** Never touch another agent's uncommitted files in the MAIN checkout.
- **Disk guard:** before snapshotting any worktree, check free space on the snapshot's drive; skip-and-record (never crash) any worktree whose snapshot would be unsafe (< 5 GB free at check time).
- **Refuse-over-guess:** any git failure during salvage of a worktree → that worktree is skipped and recorded, not removed.

---

### Task 1: Salvage tool

**Files:**
- Create: `scripts/forge/worktree_salvage.py`
- Test: `tests/test_a_worktree_is_archived_before_it_is_removed.py`

**Interfaces:**
- Produces CLI: `python scripts/forge/worktree_salvage.py salvage <worktree-path> [--repo-root R] [--apply]` (dry-run default: prints what would be archived/removed); `... restore <name> <new-path> [--repo-root R] [--apply]`; `... verify <name> [--repo-root R]`.
- Produces output contract Task 2 shells out to (CLI only; no imports needed): salvage prints a final machine-readable line `SALVAGE OK <name> head=<sha> dirty=<sha|none> files=<n> removed=<yes|no>` or `SALVAGE SKIP <name> reason=<...>`; verify prints `VERIFY OK <name> ...` / `VERIFY FAIL <name> ...` and exits nonzero on FAIL (verify is a checker, not a report — it may exit 1).
- Ref naming: `refs/archive/worktree/<name>` and `refs/archive/worktree/<name>-dirty`, `<name>` = worktree directory basename, lowercased, non-alphanumerics → `-`. On collision with an existing ref, suffix `-2`, `-3`, ...

**Behavior contract (the tests pin each):**
1. Salvage of a dirty worktree with unique commits creates both refs; the dirty snapshot commit's tree contains exactly the tracked-modified and untracked-non-ignored files (`git add -A` semantics via temp `GIT_INDEX_FILE` pointed at a copy of the worktree's index; parent = worktree HEAD; author/committer `praxis-salvage`); the worktree's own index/HEAD are untouched by the snapshot step.
2. Removal happens only with `--apply` AND only after in-process verify passes (both refs resolvable; snapshot file-count == expected non-ignored dirty count). Uses `git worktree remove --force` (justified: content archived) AFTER the junction-link check from Global Constraints.
3. A clean worktree (nothing dirty, no unique commits) still gets its HEAD ref archived (cheap, uniform), dirty ref recorded as `none`.
4. `restore` recreates a worktree at `<new-path>` checked out to the dirty snapshot (or HEAD ref when dirty=none) and prints the path — round-trip test: salvage a fixture worktree with a known dirty file, remove it, restore it, assert the dirty file's content is back.
5. Any git failure mid-salvage → `SALVAGE SKIP` line; the tool never half-removes (a worktree is removed only after its verify passed).
6. Windows junction: fixture creates a worktree with `.venv` as a `mklink /J` junction to a sibling dir (skipif non-win32); salvage --apply removes the link, target dir survives, worktree removed.

- [ ] **Step 1:** Write the failing tests for contracts 1-5 (temp-repo + worktree fixtures in the style of `tests/test_a_worktree_report_counts_what_it_would_lose.py`; reuse its `_git` helper pattern).
- [ ] **Step 2:** Run them; expect ModuleNotFoundError/usage failures.
- [ ] **Step 3:** Implement `worktree_salvage.py` (argparse subcommands; plumbing calls via subprocess; ~250-350 lines).
- [ ] **Step 4:** Tests green. Add contract-6 junction test; green on win32.
- [ ] **Step 5:** ruff check + format; wrapper commit (2 files): `feat(forge): salvage a worktree completely before anything removes it`

### Task 2: Live closure in three batches

**Files:**
- Create: `plans/thomas/tasks/PRAXIS-PHASE0-WORKTREES/closure_report.md`
- Modify: none in code

**Interfaces:** Consumes Task 1 CLI + the existing triage CLI.

- [ ] **Step 1:** Re-run triage (`--json`); partition needs-review rows: BATCH-A ordinary (no junction, not under %TEMP%), BATCH-B junction-carrying (4 known), BATCH-C %TEMP% monsters (6 known). Record partition in closure_report.md.
- [ ] **Step 2:** BATCH-A: for each, `salvage <path>` dry-run, then `salvage <path> --apply`; collect the SALVAGE OK/SKIP lines verbatim into the report. After the batch: triage again, append delta.
- [ ] **Step 3:** BATCH-B: same, confirming for each that the junction target survived (the tool asserts it; quote its output).
- [ ] **Step 4:** BATCH-C: check free disk first; salvage each with the disk guard active; any SKIP is recorded with reason and the worktree is LEFT IN PLACE.
- [ ] **Step 5:** Final state: `git worktree list` count, full list of archive refs created (`git for-each-ref refs/archive/worktree`), every SKIP with reason, and a RESTORE HOW-TO section (one command line). Target: only main + genuinely-active worktrees remain; anything skipped is enumerated, not silently surviving.
- [ ] **Step 6:** Wrapper commit of closure_report.md: `chore(worktrees): phase 0.3 closed - N archived and removed, M skipped with reasons, 0 bytes lost`

### Task 3: Prove the restore path on the real archive

- [ ] **Step 1:** Pick one mid-size archived worktree from the closure report; `restore` it to a scratch location (%TEMP% is fine); verify against the salvage OK line's files= count and spot-check 2 files with `git show <dirty-sha>:<path>`.
- [ ] **Step 2:** Remove the scratch restore (`git worktree remove --force` after the junction check — it was just created, nothing to salvage).
- [ ] **Step 3:** Append the round-trip transcript to closure_report.md; follow-up commit: `test(worktrees): the archive round-trips - restore proven on real salvage`

## Self-review notes
- Spec coverage: this plan closes phase 0.3 entirely; 0.4's tap remains queued (unchanged); no other phase touched.
- The triage tool's `removable` semantics are unused here — salvage-first supersedes them; disposition still partitions batches.
- Restore is tested BOTH on fixtures (Task 1 contract 4) and the real archive (Task 3) because a backup that has never been restored is a hope, not a backup — this repo's own lesson.
