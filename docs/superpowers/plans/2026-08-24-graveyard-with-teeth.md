# Graveyard With Teeth Implementation Plan (spec phase 1.2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Deletion becomes recorded intent with enforcement: a dead branch name cannot be pushed back, a dead file cannot ride back in on a merge, and every deliberate deletion leaves a record a gate can read.

**Architecture:** A graveyard registry (`scripts/forge/graveyard.py` + append-only `docs/ops/graveyard.json`) records branch and file deaths. Two new gates consume it: `merge_resurrection_gate.py` (staged + diff-range modes) refuses re-adding dead file paths; `dead_ref_gate.py` (pre-push) refuses re-creating dead ref names. The custodian writes branch deaths at deletion time; the janitor loses `--no-verify` and its resurrection-capable `push-new` path. The registry is seeded from history so the armed merge trap (origin/main squash, June-9 merge-base) is covered before any merge happens. Both gates ship with red-path selftests registered in `RED_PATH_CASES` — the ratchet refuses them otherwise.

**Tech Stack:** Python 3.12, pytest, git. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-24-praxis-first-design.md` §1.2. Owner delegation 2026-08-24 active.

## Global Constraints

All of `docs/superpowers/plans/2026-08-24-phase0-and-watcher-of-watchers.md` Global Constraints (wrapper commits, no double quotes, park CHANGELOG, ruff, sentence-named tests, <800 lines, no `*_part*.py`/`exec()`), plus:
- **NEVER modify SHA-pinned/protected files without the owner tap**: `scripts/crew/brief/commit.py`, anything in `enforcement_manifest.json`'s list, `agent_safety.toml`, `.pre-commit-config.yaml` if the skip-policy gate guards it (check `scripts/forge/gates/precommit_skip_policy.py` first). Wiring that requires a pinned edit goes into the Task 5 batch doc for the next tap — never worked around.
- **New enforcing gates MUST register a red-path selftest** in `tests/test_every_enforcing_gate_can_fail.py`'s `RED_PATH_CASES` (values are `(fixture_builder, expected_token)` tuples) — never added to `tests/gate_selftest_baseline.json`.
- **graveyard.json is append-only**: entries are never edited or removed by tooling; a resurrection is a NEW record (`kind: "resurrection-approved"`) referencing the death record's id.
- The janitor lives at `C:\Users\corbe\thomas-ops\janitor.py` — outside the repo, no repo gates apply there; edit carefully and smoke-test via its apply=False path.

---

### Task 1: The graveyard registry

**Files:**
- Create: `scripts/forge/graveyard.py`
- Create (seeded empty): `docs/ops/graveyard.json`
- Test: `tests/test_the_graveyard_remembers_every_deliberate_death.py`

**Interfaces (Tasks 2-4 consume):**
- `load(repo_root: Path) -> Graveyard` with `Graveyard.dead_ref_names() -> set[str]`, `Graveyard.dead_file_paths() -> dict[str, dict]` (path -> newest death record), `Graveyard.is_resurrection_approved(record_id: str) -> bool`.
- `record_death(repo_root, kind, name_or_path, dead_sha, reason, by) -> str` (returns record id `YYYY-MM-DD-<slug>-<n>`); `record_resurrection_approval(repo_root, death_id, reason, by) -> str`.
- JSON schema: `{"version": 1, "records": [{"id": str, "kind": "branch"|"file"|"resurrection-approved", "name": str, "dead_sha": str, "deleted_on": "YYYY-MM-DD", "reason": str, "by": str, "refs": str|null}]}` — `refs` holds the death record id on resurrection-approved records, else null.
- CLI: `python scripts/forge/graveyard.py record-branch|record-file|approve-resurrection|list [...]` mirroring the functions; `list --json` for consumers.

**Behavior contracts (tests pin each):** (1) record + load round-trip for both kinds; (2) append-only — recording never mutates prior records, ids unique and stable; (3) a resurrection-approved record flips `is_resurrection_approved` for its death id and ONLY that id; (4) `dead_file_paths` returns the newest record per path (a re-death after an approved resurrection makes the path dead again); (5) malformed JSON -> loud SystemExit naming the file, never a silent empty graveyard (this repo's absence-reads-as-clean disease).

- [ ] Steps: failing tests → see them fail → implement (~200 lines) → green → ruff → wrapper commit: `feat(forge): a graveyard - deletion becomes recorded intent`

### Task 2: Seed it from history

**Files:**
- Create: `scripts/forge/graveyard_seed.py` (idempotent; safe to re-run)
- Modify: `docs/ops/graveyard.json` (the seed output, committed)

**Behavior:** (a) FILE deaths: every path deleted on dev's first-parent history since merge-base `8ee07acb` (2026-06-09) and still absent from HEAD: `git log --first-parent --diff-filter=D --name-only --format=%H 8ee07acb..HEAD`, filtered to paths not in the HEAD tree; `dead_sha` = the deleting commit, reason `seeded: deleted on dev after the public-main squash point`, by `graveyard-seed`. (b) BRANCH deaths: every name under `refs/archive/` (custodian, ~80) and `refs/archive/worktree/` (salvage, 130 — strip namespace, dedupe) as branch deaths, reason `seeded: archived by custodian/salvage`. (c) Print counts; a second run adds zero records (idempotency test pins this).

- [ ] Steps: test (fixture repo with a deletion + an archive ref; seed twice; assert counts and idempotency) → implement → run against the REAL repo → commit tool + seeded JSON: `feat(forge): the graveyard is seeded - every death since the squash point is on record` (real counts in the body).

### Task 3: The merge-resurrection gate

**Files:**
- Create: `scripts/forge/gates/merge_resurrection_gate.py`
- Modify: `tests/test_every_enforcing_gate_can_fail.py` (RED_PATH_CASES entry)
- Test: `tests/test_a_dead_file_does_not_ride_back_in.py`

**Behavior:** Staged mode (default): for each staged ADDED path (`git diff --cached --name-status --diff-filter=A`), if it is in `dead_file_paths` and its death has no approved resurrection -> FAIL quoting the death record (id, deleted_on, reason) and the approval command (`graveyard.py approve-resurrection <id>`). Diff-range mode (`--base --head`) for CI: same check over `git diff --name-status --diff-filter=A base..head`. Honors `_runtime_guard.runtime_protection_disabled` like sibling gates. Exit 0 when the graveyard has no file records — but print the count consulted, never silent.
**Wiring in this task:** CI only — one invocation in `.github/workflows/gates.yml` following its existing style (verify that file is not pinned first; if pinned, move wiring to Task 5's batch). Local `commit.py` wiring is Task 5 batch material (pinned).

- [ ] Steps: failing tests (record a file death in a fixture, stage a file at that path, gate FAILs naming the record; approve resurrection, gate passes; unrelated adds pass) → implement → RED_PATH_CASES entry `(fixture, expected_token=the dead path)` → ratchet run (must stay green with NO baseline change) → ruff → commit: `feat(gates): a three-way merge cannot tell a deletion from an absence - but this gate can`

### Task 4: Dead-ref pre-push gate + janitor and custodian integration

**Files:**
- Create: `scripts/forge/gates/dead_ref_gate.py`
- Modify: `thomas/forge/branch_custodian.py` (ARCHIVE_AND_DELETE path records a branch death)
- Modify: `C:\Users\corbe\thomas-ops\janitor.py` (outside repo)
- Modify: `tests/test_every_enforcing_gate_can_fail.py` (RED_PATH_CASES entry)
- Test: `tests/test_a_dead_branch_name_stays_dead.py`

**Behavior:** (a) `dead_ref_gate.py` reads pre-push stdin format (`<local ref> <local sha> <remote ref> <remote sha>` lines) plus argv fallback `--ref <name>`; refuses any push creating a remote ref (remote sha all-zeros) whose short name is in `dead_ref_names()` without resurrection approval. (b) Custodian: after `update-ref refs/archive/<name>` succeeds in archive-and-delete, call `graveyard.record_death(kind=branch, ...)` — import-guarded so the custodian still works if graveyard is absent (log, never crash). (c) Janitor: remove `--no-verify` from `rescue_push`; before any `push-new`, consult the graveyard via `graveyard.py list --json` and demote a dead-named branch to a report line (`SKIP dead-name <name> per graveyard <id>`) instead of pushing. Janitor changes verified by smoke run on its apply=False path against a temp repo; diff quoted verbatim in the report (thomas-ops has no suite — do not invent one there).
**Wiring:** pre-push hook entry in `.pre-commit-config.yaml` IF unpinned (check first); otherwise Task 5 batch.

- [ ] Steps: failing tests (dead name refused on create-push stdin; alive name passes; approved resurrection passes) → implement → RED_PATH_CASES entry → ratchet green, no baseline change → custodian change + test (fixture custodian delete writes a graveyard record) → janitor edit + smoke transcript → ruff → commits (repo files via wrapper, ≤3 code files each; janitor.py is a plain edit, noted in report): `feat(gates): a dead branch name stays dead`

### Task 5: Wiring batch for the next tap + closure

**Files:**
- Create: `plans/thomas/tasks/PRAXIS-PHASE1-BREAKGLASS/batch.md`

**Behavior:** Enumerate exactly which wiring needed a pinned edit and was deferred (commit.py LOCAL_GATE_COMMANDS entries for both gates; `.pre-commit-config.yaml` entries if pinned; manifest re-bless covering the two new gate scripts + any touched pinned file), in the executed phase-0 batch.md format (run order, verify commands, `STATUS: PREPARED - awaiting owner tap.` line). Also verify the ratchet sees both new gates as enforcing (via the gates.yml wiring) with RED_PATH_CASES coverage and no baseline entries. Commit: `docs(phase1): the graveyard wiring batch - prepared for your next tap`

## Self-review notes
- Spec 1.2 coverage: refs (custodian record + pre-push gate + janitor demotion) ✔; files (records return + merge gate + CI range mode) ✔; standing hazard (Task 2 seeds June-9..HEAD deletions before any merge can fire) ✔.
- The ratchet integration is the plan's own enforcement: the new gates cannot land unwatched.
- Janitor edits are outside repo gates — the report carries the diff verbatim for the record.
- **The spec was narrowed twice during implementation, both deliberately (fix-wave review 2026-08-25, M8/M9):**
  1. **Only `ARCHIVE_AND_DELETE` writes a death record; `CONTAINED` deletions do not.** The spec's "every deliberate deletion leaves a record" reads as covering both retirement paths the custodian has (`DELETE` for `CONTAINED` branches, `ARCHIVE_AND_DELETE` for `SUPERSEDED` ones), but only the latter calls `_record_branch_death`. This is the better design, not a shortfall: a `CONTAINED` branch has zero commits outside trunk by definition — there is no unique sha for a death record to name, and no `refs/archive/<name>` ref for a later resurrection to be refused against, because nothing about it could ever look like a resurrection worth gating. Recording a death for it would add a graveyard entry that no gate could ever meaningfully consult. `SUPERSEDED` branches are the ones that get an archive ref and therefore a real dead-sha the pre-push gate can refuse a push against — exactly the case the registry exists for.
  2. **The "sole-custodian routing rule" implied by the spec's architecture line was substituted with refusal gates plus janitor defang.** The spec frames the graveyard as something one writer path (the custodian) feeds and one reader (a gate) consults; what actually shipped is two independent refusal gates (`merge_resurrection_gate.py`, `dead_ref_gate.py`) that consult the registry regardless of who wrote it, plus the janitor losing `--no-verify` and its resurrection-capable `push-new` path (Task 4). This is the better substitution: routing every death through one custodian would make the registry only as trustworthy as that one code path, whereas the gates enforce the invariant ("a dead name/path needs an explicit approval to come back") at the point of re-entry, independent of who or what tried to kill or revive it. The janitor defang closes the one write path that could route around the gates entirely (a rescue push bypassing pre-push hooks with `--no-verify`) rather than trying to make the janitor a second correct writer.
