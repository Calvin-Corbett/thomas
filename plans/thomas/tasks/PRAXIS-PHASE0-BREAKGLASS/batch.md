# Phase 0.4 break-glass batch: monolith baselines + manifest re-bless

This is a **prepared** action list, not an executed one. Nothing in this file
has been run. It exists so you can review the four choices below and then
sign the whole batch with one Windows Hello tap, in the run order at the
bottom.

Source spec: `docs/superpowers/specs/2026-08-24-praxis-first-design.md`,
Phase 0 item 4: "monolith baselines (or pre-splits) for `loop_execution.py`
(982), `llm_client.py` (833), `run_store.py` (929), `commit.py` (846);
enforcement manifest re-bless for the gate/crew files the ports refactor
touches."

---

## (a) The four files: measured counts and the baseline-vs-split call

Re-measured 2026-08-24 with `wc -l` (spec cited 982/833/929/846 — the tree
moves, so these are today's real counts, not the spec's):

| File | Spec count | Measured count | Choice |
|---|---|---|---|
| `thomas/agent/loop_execution.py` | 982 | **982** | Baseline |
| `thomas/core/llm_client.py` | 833 | **833** | Baseline |
| `thomas/marketplace/observability/run_store.py` (spec cites `thomas/core/run_store.py`, see below) | 929 | **929** | Baseline |
| `scripts/crew/brief/commit.py` | 846 | **846** | Baseline |

**Path correction:** the spec and this task's own brief both cite the third
file as `thomas/core/run_store.py`. That path does not exist and has no git
history (`git log --all -- thomas/core/run_store.py` is empty). The file at
929 lines — matching the spec's count exactly — is
`thomas/marketplace/observability/run_store.py`. Use that path in the actual
baseline/approval entries; the spec's path is stale.

**Context on the cap these four are measured against:** `scripts/forge/gates/monolith_guard.py --help`
confirms the guard reads a baseline JSON (default `docs/monolith_guard_baseline.json`)
with a `--base`/`--head` growth check. Reading that baseline file directly:
`hard_limits.py = 1200`, and `waiver_policy.unbaselined_soft_limit_lines = 800`
with `enforce_soft_limit_changed_only = true`. All four files sit **under**
the 1200-line hard limit already; they sit **over** the 800-line soft limit,
which only fires when a file is in the diff's changed-file set. None of the
four is in that set today (none of Tasks 1-5 touch them), so the gate is
silent on them right now — but it will not stay silent once phase 1.3 or a
`commit.py` edit lands a change to any of them.

**Per-file reasoning (one line each):**

- **`thomas/agent/loop_execution.py`** — Baseline. Spec 1.3 names this file's
  owning module by function: it's one of the ~24 call sites that build
  message lists for the LLM client capture hook (`docs/superpowers/specs/2026-08-24-praxis-first-design.md`
  section 1.3). A pre-split now would draw module boundaries before 1.3's
  capture-hook boundary is designed, and 1.3 lands next — the split would
  likely be redrawn within the same phase.
- **`thomas/core/llm_client.py`** — Baseline. Spec 1.3 states the boundary
  explicitly: "the LLM client, not any message builder... the client is the
  narrow waist they all pass through. A capture hook there records the exact
  message list entering every request." Reading the file confirms the shape:
  almost all of it is one `LLMClient` class. Splitting it before the capture
  hook is designed risks a boundary that gets crossed immediately by 1.3's
  own change.
- **`thomas/marketplace/observability/run_store.py`** — Baseline. Spec 1.3
  says the session log "extends the existing `run_store` spine (run_id + seq
  + append; NDJSON replay), subsuming the forge event transcript as a view."
  This file is getting new responsibility, not just more lines of the old
  kind; splitting it ahead of that design would guess at boundaries 1.3 is
  about to set.
- **`scripts/crew/brief/commit.py`** — Baseline, with lower confidence than
  the other three. Spec 3.1 ("Gate registry") names this file directly:
  "`commit.py` / `land_checks.py` / `safety_init.py` replace hardcoded gate
  tuples (~60 literal-path sites) with a data-driven registry." Reading the
  file confirms a real seam already exists — `LOCAL_GATE_COMMANDS` (line 39)
  is a single tuple-of-tuples separate from the orchestration logic in
  `commit_scoped_changes` (line 517) — so a pre-split along that seam
  wouldn't be a guess. The reason to still baseline rather than split now:
  3.1 is phase 3, the last phase, ordered behind six other 1.x/2.x items
  ("each capability protects the ones after it"); its registry design isn't
  specified beyond the one sentence above, so a pre-split today could still
  land on the wrong side of whatever the data-driven registry ends up
  needing. Baseline first; revisit when 3.1 is actually scheduled, not on
  1.3's clock like the other three.

None of these four files currently has an entry in
`docs/monolith_guard_baseline.json`'s `allowed_large_files` (checked: 4
existing entries, none matching any of the four paths above), so all four
choices below are **new** baseline entries, not extensions of existing ones.

### The baseline entry shape — two files, two different shapes (read both before editing either)

The brief for this task asked for "the field shape used by
`docs/ops/monolith_baseline_approvals`... read one existing entry there and
copy its shape," expecting that shape to carry "expiry date, owner, and
max_growth." That expectation doesn't match what's actually in that file.
There are **two separate JSON files** involved, serving two different gates,
and the expiry/owner/max_growth fields live in only one of them:

**1. `docs/monolith_guard_baseline.json`** — the actual enforcement config
read by `monolith_guard.py`. Its `allowed_large_files` entries carry exactly
the shape the brief described. One existing entry, copied verbatim:

```json
"thomas/cli/repl.py": {
  "owner": "thomas-core",
  "expires_on": "2026-06-30",
  "max_lines": 2000,
  "max_growth_lines": 0,
  "reason": "REPL modularization is in-progress; bounded waiver until split lands."
}
```

**2. `docs/ops/monolith_baseline_approvals.json`** — a separate approval
ledger, read by a separate gate (`scripts/forge/gates/monolith_baseline_approval_gate.py`).
This file exists and is non-empty (9 entries), so the "if it doesn't exist,
derive from the gate source" fallback doesn't trigger — but its real shape
has **no** expiry, owner, or max_growth field at all. One existing entry,
copied verbatim:

```json
{
  "id": "2026-02-25-thomas-preferences-store-new-baseline",
  "path": "thomas/preferences/store.py",
  "change": "new_baselined_file",
  "new_value": 869,
  "approved_by": "core-platform",
  "approved_on": "2026-02-25",
  "reason": "Temporary baseline entry while preferences runtime/store responsibilities are decomposed."
}
```

Reading `monolith_baseline_approval_gate.py` directly (`_approval_matches`,
line 161; `_find_relaxations`, line 101) confirms why both are needed and
why the shapes differ: the gate diffs `docs/monolith_guard_baseline.json`
between base and head ref, and for every new/relaxed entry it finds there
(`change` = `new_baselined_file`, `max_lines_increase`, or
`max_growth_lines_*`), it requires a **matching row** in the approvals
ledger with a non-empty `approved_by`, `approved_on`, and `reason`, and a
`new_value` matching the relaxation's `new_value`. It also fails the commit
outright if the baseline file changed but the approvals file did not
(`apply_approval_file_change_requirement`, line 216) — so both files must be
edited together, or this gate blocks the tap.

**The four proposed entries, both shapes, ready to paste:**

`docs/monolith_guard_baseline.json` → add to `allowed_large_files`:

```json
"thomas/agent/loop_execution.py": {
  "owner": "thomas-core",
  "expires_on": "2026-09-30",
  "max_lines": 1100,
  "max_growth_lines": 0,
  "reason": "Message-list boundary for phase 1.3 session-log capture hook; split lands as part of that phase, not before."
},
"thomas/core/llm_client.py": {
  "owner": "thomas-core",
  "expires_on": "2026-09-30",
  "max_lines": 950,
  "max_growth_lines": 0,
  "reason": "Narrow-waist client for phase 1.3 session-log capture hook; split lands as part of that phase, not before."
},
"thomas/marketplace/observability/run_store.py": {
  "owner": "thomas-core",
  "expires_on": "2026-09-30",
  "max_lines": 1050,
  "max_growth_lines": 0,
  "reason": "Extended by phase 1.3 (run_id/seq/append spine subsumes the forge event transcript); split lands as part of that phase, not before."
},
"scripts/crew/brief/commit.py": {
  "owner": "thomas-core",
  "expires_on": "2026-11-30",
  "max_lines": 950,
  "max_growth_lines": 0,
  "reason": "LOCAL_GATE_COMMANDS seam awaits phase 3.1's data-driven gate registry; longer runway than the other three since 3.1 is phase 3, not phase 1."
}
```

`docs/ops/monolith_baseline_approvals.json` → add to `approvals` (each
`new_value` matches the `max_lines` above, each `id` follows the existing
`YYYY-MM-DD-<slug>-new-baseline` naming convention seen in the file):

```json
{
  "id": "2026-08-24-thomas-agent-loop-execution-new-baseline",
  "path": "thomas/agent/loop_execution.py",
  "change": "new_baselined_file",
  "new_value": 1100,
  "approved_by": "<your approval name>",
  "approved_on": "2026-08-24",
  "reason": "Message-list boundary for phase 1.3 session-log capture hook; split lands as part of that phase, not before."
},
{
  "id": "2026-08-24-thomas-core-llm-client-new-baseline",
  "path": "thomas/core/llm_client.py",
  "change": "new_baselined_file",
  "new_value": 950,
  "approved_by": "<your approval name>",
  "approved_on": "2026-08-24",
  "reason": "Narrow-waist client for phase 1.3 session-log capture hook; split lands as part of that phase, not before."
},
{
  "id": "2026-08-24-thomas-observability-run-store-new-baseline",
  "path": "thomas/marketplace/observability/run_store.py",
  "change": "new_baselined_file",
  "new_value": 1050,
  "approved_by": "<your approval name>",
  "approved_on": "2026-08-24",
  "reason": "Extended by phase 1.3 (run_id/seq/append spine); split lands as part of that phase, not before."
},
{
  "id": "2026-08-24-thomas-crew-brief-commit-new-baseline",
  "path": "scripts/crew/brief/commit.py",
  "change": "new_baselined_file",
  "new_value": 950,
  "approved_by": "<your approval name>",
  "approved_on": "2026-08-24",
  "reason": "LOCAL_GATE_COMMANDS seam awaits phase 3.1's data-driven gate registry."
}
```

`<your approval name>` is a placeholder — the approval gate requires this field to be
non-empty (`_approval_matches`, line 169), so fill it with whatever name you
sign break-glass approvals with today before this batch is executed.

`max_lines` above is set roughly 100-120 lines over today's measured count
per file (not a round number, not the current count exactly), so each file
has working room without inviting silent growth — `max_growth_lines: 0`
still means the guard's growth check (`--base`/`--head`) fails on any
increase once that mode is enabled for these gates, per `monolith_guard.py --help`.
Adjust the numbers if you want a different margin; the shape and the
approval-ledger requirement don't change.

---

## (b) Enforcement manifest re-bless

**Regeneration command** (found via `grep -rn "manifest" scripts/forge/gates/enforcement_integrity.py`,
which shows `generate_manifest()` at line 108, wired to `--generate-manifest`
at line 139, and the script's own docstring/comment at lines 133-134 calling
this "a human-only operation"):

```
python scripts/forge/gates/enforcement_integrity.py --generate-manifest
```

This overwrites `scripts/forge/gates/enforcement_manifest.json` with a fresh
SHA-256 hash for every path listed in `agent_safety.toml`'s
`[protected].enforcement_scripts` (59 files today — read, not modified, to
produce this count). It does not touch `agent_safety.toml` itself.

**What's already stale, right now, in the working tree** (this task did not
create or touch this diff — confirmed present at session start and left
untouched, per `git status --porcelain -- scripts/forge/gates/enforcement_manifest.json`
showing only ` M` throughout this task):

- `scripts/forge/gates/monolith_guard.py` — its hash in
  `enforcement_manifest.json` no longer matches the working file, but NOT for
  the reason previously written here. This is not a landed reformat. The
  file's last landed commit is `c7f5a84f` (2026-06-02); everything since is
  an **uncommitted, unreviewed working-tree diff of ~28 lines that changes
  behavior**: the CLI's default repo-root resolution moves from
  `parents[1]` to `parents[3]` (the July defect's actual fix — the old value
  resolved to `scripts/forge`, not the repo root, so `--staged-only` runs
  with no `--repo-root` silently scanned nothing), plus a new scoped-files
  fast path that walks only the named files instead of the whole tree.
  Verify yourself with `git log -1 --format=%H -- scripts/forge/gates/monolith_guard.py`
  and `git diff -- scripts/forge/gates/monolith_guard.py`.

  The manifest is also stranger than "stale": today's working-tree manifest
  entry for this file (`8883aff1...`) matches **neither** HEAD's committed
  file (hash `1177ff2a...`, matching the manifest entry at `c7f5a84f`) **nor**
  today's working file (hash `9305d9a8...`, verify with
  `python -c "import hashlib;print(hashlib.sha256(open('scripts/forge/gates/monolith_guard.py','rb').read()).hexdigest())"`).
  That manifest entry is an orphan manual edit from neither state — step (b)'s
  regeneration would silently overwrite it with no record of what it was
  blessing.

  **PRECONDITION before step (b)'s manifest regen runs**: the
  `monolith_guard.py` working-tree change above must first be either landed
  through code review together with its red-path test (untracked
  `tests/test_a_gate_must_scan_the_repository_it_guards.py`, another agent's
  pending work) or reverted. The manifest regen must never bless an
  unreviewed working-tree state — run it only after that diff has one of
  those two outcomes, not before.

**What phase 1 will change next**, so the re-bless right after this batch's
manifest regen won't already be stale again in a week:

- `scripts/crew/brief/commit.py` — already in the protected list; phase 1.2's
  "sole-custodian rule" text ("the janitor and every other pusher route
  through the custodian") implies routing `commit.py`'s push/land path through
  a custodian, and phase 3.1's gate-registry work (section (a) above) touches
  it again later. Expect at least one more hash change here before phase 1
  finishes.
- Any **new** gate file phase 1.2 introduces (the spec names "a pre-push gate
  refuses re-creating a dead name" and "a merge gate diffs any incoming merge
  against the graveyard") is not yet in `agent_safety.toml`'s protected list
  (it doesn't exist yet), so it isn't in today's manifest either. Adding a new
  enforcing gate means: write the gate, add its path to
  `agent_safety.toml [protected].enforcement_scripts`, then regenerate the
  manifest — that `agent_safety.toml` edit is itself a protected-file change
  and needs your sign-off separately from this batch.
- `thomas/core/llm_client.py`, `thomas/agent/loop_execution.py`,
  `thomas/marketplace/observability/run_store.py` (section (a) above) are
  **not** in `agent_safety.toml`'s protected list today, so phase 1.3's
  capture-hook work on them will not, by itself, change
  `enforcement_manifest.json` — only the baseline/approval files above.

This batch's manifest regen re-blesses the one known-stale hash
(`monolith_guard.py`) now. It is not a promise that the manifest stays fresh
through the rest of phase 1 — expect this same "regen + re-bless" tap to
recur at least once more when `commit.py`'s custodian routing lands, and
again whenever phase 1.2's new gate file is registered.

---

## (c) Run order

Everything below is one pass you sign with a single tap. Nothing executes until you run
step 1.

1. `python scripts/breakglass_window.py on` — opens the time-boxed approval
   window with one Windows sign-in (per `scripts/breakglass_auth.py` /
   `scripts/breakglass_window.py`, the standing break-glass flow named in
   this task's brief).
2. Edit `docs/monolith_guard_baseline.json` — add the four `allowed_large_files`
   entries from section (a).
3. Edit `docs/ops/monolith_baseline_approvals.json` — add the four matching
   `approvals` entries from section (a), with `approved_by` filled in.
4. Run `python scripts/forge/gates/enforcement_integrity.py --generate-manifest`
   — re-blesses `scripts/forge/gates/enforcement_manifest.json` against the
   current `monolith_guard.py` (and anything else already changed under
   `agent_safety.toml`'s protected list at the time you run this).
5. Review the diff on all three touched files
   (`docs/monolith_guard_baseline.json`, `docs/ops/monolith_baseline_approvals.json`,
   `scripts/forge/gates/enforcement_manifest.json`) before committing.
6. `python scripts/breakglass_window.py off` — closes the window.

---

STATUS: EXECUTED 2026-08-24 via owner Windows Hello (window + runtime-protection toggle, both re-armed immediately after). Landed as commit db808bdf: reviewed monolith_guard repo-root fix + red-path test, four time-boxed baselines with ledger approvals, manifest re-signed (59 scripts, PASS).
