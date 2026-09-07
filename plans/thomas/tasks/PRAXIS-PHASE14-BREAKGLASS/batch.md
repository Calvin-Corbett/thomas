# Phase 1.4 break-glass batch: the evidence gate becomes local law

This is a **prepared** action list, not an executed one. Nothing in this
file has been run. It exists so you can review the choices below and then
sign the whole batch with one Windows Hello tap, in the run order at the
bottom.

Source spec: `docs/superpowers/specs/2026-08-24-praxis-first-design.md`
§1.4. Companion doc:
`plans/thomas/tasks/PRAXIS-PHASE14-CLAIMS/status.md` (what verifies, what
doesn't, what expires, today).

`scripts/forge/gates/workboard_evidence_gate.py` landed CI-enforcing
(`.github/workflows/gates.yml`'s diff-range job) in phase 1.4 task 4, but it
is still **unpinned**: not in `agent_safety.toml`'s `enforcement_scripts`,
not integrity-checked by `enforcement_manifest.json`, and not run locally by
`scripts/crew/brief/commit.py`. CI is the only place it runs today. This
batch promotes it to the same standing every other landing-time gate has.

---

## (a) Promote `workboard_evidence_gate.py` into enforcement + re-bless the manifest

**Current state, verified against the tree**: `agent_safety.toml`'s
`[protected].enforcement_scripts` list has **61** entries today (counted by
loading the TOML directly); `scripts/forge/gates/enforcement_manifest.json`
already has exactly 61 keys matching it 1:1 -- both are in sync right now
(no stale drift the way the phase-0 batch found for `monolith_guard.py`).
`workboard_evidence_gate.py` is not among either list.

**The edit**: add one line to `agent_safety.toml`'s `enforcement_scripts`
array (the "── Agent commit path ──" section is the natural home, next to
`scripts/crew/brief/commit.py`, since this gate is invoked from the same
local commit path this batch's part (b) wires it into):

```toml
"scripts/forge/gates/workboard_evidence_gate.py",
```

This takes the list from 61 -> 62 entries.

**Regeneration command** (same "human-only operation" the phase-0 batch
used, `scripts/forge/gates/enforcement_integrity.py --generate-manifest`,
confirmed unchanged at that call site since):

```
python scripts/forge/gates/enforcement_integrity.py --generate-manifest
```

This overwrites `scripts/forge/gates/enforcement_manifest.json` with a fresh
SHA-256 hash for all 62 paths now listed in `agent_safety.toml`. It does not
touch `agent_safety.toml` itself, and it does not touch any file's content
-- only the manifest's record of what each protected file's hash should be.

---

## (b) `commit.py` LOCAL_GATE_COMMANDS entry

**Current state**: `scripts/crew/brief/commit.py`'s `LOCAL_GATE_COMMANDS`
tuple (line 39) runs 20+ gates locally at commit time; none of them is
`workboard_evidence_gate.py` today (grep-confirmed). The nearest precedent
in shape and invocation style is the `merge_resurrection` entry, which also
diffs `WORKBOARD`-adjacent state and also defaults to staged mode with no
extra flags:

```python
("merge_resurrection", (sys.executable, "scripts/forge/gates/merge_resurrection_gate.py")),
```

**The edit** -- add, styled identically:

```python
("workboard_evidence", (sys.executable, "scripts/forge/gates/workboard_evidence_gate.py")),
```

**Why no extra flags is the correct call, not an oversight**: the gate's own
default mode (no `--base`) is "staged" -- it diffs `HEAD:<workboard>`
against the STAGED index blob (`git show :plans/thomas/WORKBOARD.md`), which
is exactly the signal a local pre-commit hook has and exactly what
`merge_resurrection_gate.py` already does the same way at this same call
site. The `--base`/`--head` diff-range flags exist for CI, where there is no
staged index, only two refs -- `.github/workflows/gates.yml`'s own
invocation already supplies those, unchanged by this batch. Passing
`--run-store-db` here is a separate, later decision (see the CI follow-up in
`status.md`): omitting it locally is consistent with omitting it in CI
today, and run-kind evidence still PASSES (as `UNAVAILABLE`, not silently
green and not a false FAIL) either way.

---

## (c) OPTIONAL owner decision: promote `evidence=` to a required field in `workboard_claims.py`

**This is not pre-decided. Read the trade-off before choosing.**

`scripts/forge/gates/workboard_claims.py` (pinned) validates every `##
Active Tasks` line against `REQUIRED_ACTIVE_TASK_FIELDS = ("task_id",
"agent", "scope", "summary", "status")` (line 30) -- unconditionally, for
every line regardless of that line's `status` value. `_parse_active_task_entry`
(line 372) calls `_parse_kv_fields(..., required_fields=REQUIRED_ACTIVE_TASK_FIELDS)`
with no branch on status.

**The trade-off that matters**: naively adding `"evidence"` to that tuple
would require an `evidence=` field on **every** Active Task line -- queued,
claimed, in_progress, and review lines too, not only `done` ones. That is
not what phase 1.4 wants (evidence is meaningless before a task is done) and
would need real code, not a one-line tuple edit: `_parse_active_task_entry`
would need a status-conditional check (`evidence` required only when
`status == "done"`), which is a `workboard_claims.py` change with its own
review, since that file is pinned.

Even done correctly (status-conditional), this is a load-bearing behavior
change: today, a `status=done` line with no evidence is caught SOFTLY, after
the fact, by `claim_evidence_sweep.py`'s legacy-drain path (`"legacy done
without evidence"`, expires on the first sweep pass, no TTL gate) or by
`workboard_evidence_gate.py` at landing time if the transition is fresh in
the diff. Promoting `evidence` to a hard-required field in the pinned parser
changes this to a HARD failure at `evaluate_board` time -- the whole
workboard fails to parse, not just the one line -- for any `status=done`
line that predates evidence recording (phase 1.4 task 2) and has not yet
been through a sweep pass. `## Active Tasks` on this workboard is empty
right now (`plans/thomas/WORKBOARD.md`, confirmed: `- none`), so there is no
LIVE breakage today -- but the moment any legacy-shaped done line reappears
(a stale branch merge, a hand-edit, an agent that doesn't go through
`reactivate.set_task_status`), the pinned validator would refuse to parse
the board at all, which is a harder failure mode than the sweep's graceful
per-task expiry.

**Recommendation: defer this promotion until the legacy drain has had a
chance to run empty** -- i.e., until `claim_evidence_sweep.py`'s
`"legacy done without evidence"` case has had at least one full sweep cycle
against the real workboard with nothing left for it to catch. The sweep's
whole design point is to retire legacy-shaped done lines one at a time, with
a message to the agent that held the claim; promoting the hard requirement
before that drain empties throws away that softness for no benefit, since
the two mechanisms would otherwise be catching the exact same lines at the
exact same time. This is a recommendation, not a decision this batch makes
for you -- if you want it done anyway, say so and it becomes a task 6.

---

## (d) Run order

**SUPERSEDED by section (i) below (final-review fix wave, 2026-08-26,
Critical-2).** This list's step 4 regenerates the manifest BEFORE step 5
edits `commit.py` — but `commit.py` is itself in `enforcement_scripts`
(manifest-hashed), so that order freezes a hash step 5 immediately
invalidates, hard-blocking step 8's commit with no instruction for what to
do. Do not follow this list in isolation. It is left in place, unedited
below, as the record of what phase 1.4 originally prepared; section (i)
carries the corrected order for the whole batch, phases 1.4 and 1.5 both.

Everything below is one pass you sign with a single tap. Nothing executes
until you run step 1. Two separate break-glass mechanisms are involved, the
same two the phase-0 batch used and re-armed afterward: the **window**
(human-presence tap, gates a protected-file edit) and the **toggle**
(disables `runtime_protection_disabled`-aware gates outright while it's
off). Both must be re-armed at the end regardless of how the tap goes.

1. `python scripts/breakglass_window.py on` -- opens the time-boxed
   human-presence window (one Windows sign-in) that
   `protected_files_gate.py`'s breakglass/approval-trailer path checks.
2. `python scripts/runtime_protection_toggle.py off` -- disables the
   `runtime_protection_disabled`-aware gates (`protected_files_gate.py`
   among them) for the duration of this edit. Requires its own Windows
   credential prompt.
3. Edit `agent_safety.toml` -- add the `workboard_evidence_gate.py` line
   from section (a) to `enforcement_scripts` (61 -> 62).
4. Run `python scripts/forge/gates/enforcement_integrity.py
   --generate-manifest` -- re-blesses `scripts/forge/gates/enforcement_manifest.json`
   against the new `agent_safety.toml` list (62 entries).
5. Edit `scripts/crew/brief/commit.py` -- add the `workboard_evidence`
   tuple from section (b) to `LOCAL_GATE_COMMANDS`.
6. (c) is optional and separate -- only if you decide to promote `evidence`
   to required in `workboard_claims.py`, and only after writing the
   status-conditional check the trade-off above describes, not a bare tuple
   edit.
7. Review the diff on every touched file (`agent_safety.toml`,
   `scripts/forge/gates/enforcement_manifest.json`, `scripts/crew/brief/commit.py`,
   and `scripts/forge/gates/workboard_claims.py` only if (c) was taken)
   before committing.
8. `python scripts/runtime_protection_toggle.py on` -- re-arms runtime
   protection.
9. `python scripts/breakglass_window.py off` -- closes the human-presence
   window.

**Verify commands** (run after landing, before considering this batch
closed):

```
python scripts/forge/gates/enforcement_integrity.py            # integrity check passes against the new manifest
python scripts/forge/gates/workboard_evidence_gate.py           # local staged-mode run, should PASS/no-op on a clean board
python scripts/crew/brief/commit.py --help                      # confirms commit.py still imports cleanly with the new entry
```

---

## Phase 1.5 additions (amended 2026-08-25)

Source spec: `docs/superpowers/specs/2026-08-24-praxis-first-design.md` §1.5.
Companion doc: `plans/thomas/tasks/PRAXIS-PHASE15-FORGING/status.md` (the
loop's shape, what enforces where, follow-ups, today).

`scripts/forge/gates/problem_closure_gate.py` landed CI-enforcing in phase
1.5 (registered in `RED_PATH_CASES`, wired into `.github/workflows/gates.yml`'s
diff-range job), but like `workboard_evidence_gate.py` above it is still
**unpinned**: verified by grep, it has zero matches in `agent_safety.toml`,
`scripts/forge/gates/enforcement_manifest.json`, `scripts/crew/brief/commit.py`,
and `.pre-commit-config.yaml`. This section amends the SAME prepared tap to
promote it too, rather than opening a second break-glass ceremony for the
same window. Nothing below has executed either — the whole batch, phase 1.4
and phase 1.5 together, is still signed by the one run in section (i).

### (e) Promote `problem_closure_gate.py` into enforcement + extend the re-bless

**Current state, verified against the tree (2026-08-25, after phase 1.5
landed on `dev`, before this tap has run)**: `agent_safety.toml`'s
`enforcement_scripts` list is still **61** entries and the manifest is still
**61** keys, in sync — section (a)'s edit above has not executed yet either.
`problem_closure_gate.py` is not among either list.

**The edit**: add a second line to the same array, in the same
"── Agent commit path ──" section as section (a)'s new line, for the
identical reason (this gate is also invoked from the local commit path
section (g) below wires it into):

```toml
"scripts/forge/gates/problem_closure_gate.py",
```

**Combined count**: section (a)'s line plus this line take
`enforcement_scripts` from **61 to 63** entries — not 61→62 twice. Both
lines land in the same edit pass (step 3 of the integrated run order below),
so `enforcement_integrity.py --generate-manifest` runs once, against the
final 63-entry list, not once per gate.

### (f) `.pre-commit-config.yaml` hook

**Precedent, verified by grep**: `workboard_task_problems.py` — the closure
gate's nearest sibling in the problem-resolution family — is wired into
*both* `commit.py`'s `LOCAL_GATE_COMMANDS` (line 64) *and*
`.pre-commit-config.yaml` (the `thomas-workboard-task-problems-gate` hook).
`workboard_evidence_gate.py` in section (b) above only got the `commit.py`
half; this batch gives the closure gate the full double wiring its sibling
already has, since this tap is the first natural chance to add it.

**The edit** — add, after the existing `thomas-workboard-task-problems-gate`
hook (grouping only, not load-bearing):

```yaml
      - id: thomas-problem-closure-gate
        name: Thomas Problem Closure Gate
        entry: python scripts/_gate_python.py scripts/forge/gates/problem_closure_gate.py
        language: system
        pass_filenames: false
```

No extra flags, for the same reason section (b) gives for the evidence gate:
the gate's own default (no `--base`) is staged mode — exactly the signal a
local pre-commit hook has.

### (g) `commit.py` LOCAL_GATE_COMMANDS entry

**The edit** — add, styled identically to the `workboard_task_problems`
entry it sits beside:

```python
("problem_closure", (sys.executable, "scripts/forge/gates/problem_closure_gate.py")),
```

### (h) `docs/ops/accepted_risks.json` -> `[protected].enforcement_files`

**Why**: Task 1's report flagged this as protection debt explicitly not
paid in that task (`agent_safety.toml` was pinned for Task 1).
`docs/ops/accepted_risks.json` has the identical shape and the identical
reason to be protected as `docs/ops/graveyard.json`, already in this list —
both are append-only registries a gate trusts as a resolution authority, and
the closure gate trusts this one the same way the graveyard is trusted, so
it must not be silently editable.

**The edit** — add one line to `[protected].enforcement_files`, immediately
after `"docs/ops/graveyard.json"`:

```toml
"docs/ops/accepted_risks.json",
```

**Note**: this list is `enforcement_files`, a different array from
`enforcement_scripts` — confirmed by reading `enforcement_integrity.py`
(`data.get("protected", {}).get("enforcement_scripts", [])`, line 70): the
manifest hashes `enforcement_scripts` only. Adding `accepted_risks.json` to
`enforcement_files` does not change the 63-entry `enforcement_scripts` count
in section (e), and does not add a key to the manifest — it is protected via
`protected_files_gate.py`, the same mechanism that already protects
`docs/ops/graveyard.json`, not via the integrity manifest.

## Phase 2 addition (amended 2026-08-26, Task 2 — salvage debris tombstones)

Source: `docs/superpowers/plans/2026-08-25-phase2-repairs-batch1.md` Task 2;
`.superpowers/sdd/2026-08-25-phase2-repairs-batch1/task-2-report.md`. Not a
new ceremony — this rides the SAME open protection window as (a)-(h) above,
since both need the identical one-tap human presence and there is no reason
to require a second Windows Hello sign-in for two unrelated protected-file
edits landing the same day.

**What's pending**: `docs/ops/graveyard.json` (protected `enforcement_file`
since `28518073`, the phase-1.2 graveyard-wiring landing — corrected here
from an earlier report draft that mis-cited `e6731922`) has a real,
already-written, uncommitted delta in the working tree: four `kind="file"`
death records appended via the actual `scripts/forge/graveyard.py
record-file` API (never hand-edited), recording the deletion of four
salvage-debris orphans — `thomas/server/app_part03.py`, `apps/site/src/app/
globals_part01.css`, `globals_part02.css`, `globals_part03.css`. **Only
`thomas/server/app_part03.py`'s deletion actually landed** in `chore(server):
salvage debris dies on the record - four orphans, four tombstones` — a
second, independent blocker surfaced landing the other three: their
deletion trips `scripts/forge/gates/site_visual_proof.py` with a
37-60% footer-focus pixel-diff against the committed baseline, reproduced
with the three files BOTH present and deleted (pre-existing, non-
deterministic baseline drift on `dev`, not caused by this deletion — see
that commit's message and `tests/test_salvage_debris_stays_dead.py`'s
docstring for the full investigation). The three CSS files are therefore
deleted on disk and have graveyard records on disk, same as
`app_part03.py`, but their deletion is a SEPARATE, not-yet-landed commit,
unrelated to this protected-files tap and not fixed by it — this window
only lands the graveyard.json append below, which covers all four records
regardless of which deletions have landed.

**Verified this is the ONLY uncommitted delta in that file** —
`git diff --stat docs/ops/graveyard.json` reports exactly `40 insertions(+),
0 deletions(-)`, and the full diff is a pure append after the last existing
record: nothing earlier in the file is touched. The four new ids, in append
order:

```
2026-08-26-thomas-server-app-part03-py-1
2026-08-26-apps-site-src-app-globals-part01-css-1
2026-08-26-apps-site-src-app-globals-part02-css-1
2026-08-26-apps-site-src-app-globals-part03-css-1
```

Each record's `reason` names `salvage-debris`, cites
`.superpowers/sdd/2026-08-25-phase2-recon/recon.md` Section 3c / Section 4
#4, and the `36ad0730 praxis-salvage snapshot of full (10613 files)` root
both orphan sets trace to. `by` is `claude` on all four. This is what the
signer is committing — nothing more.

**Recovery block (fix round 1, review finding I1) — this append is NOT
byte-recoverable from any other committed source.** `.superpowers/sdd/` is
gitignored wholesale, so the recon and this task's report are machine-local
only; if the local working tree that produced this delta is ever lost
before the tap (`git checkout -- .`, `git stash` dropped, a fresh clone,
this being a live shared checkout other sessions commit into) there is
nothing else in git history that reproduces it byte-for-byte. Two recovery
paths, in priority order:

**Primary — append these four objects verbatim.** This is primary because
it preserves the exact ids this document already cites above (re-recording
via `record-file` instead generates NEW ids stamped with whatever date the
re-record happens on, which would silently invalidate the id list and the
"40 insertions" claim above). If `docs/ops/graveyard.json` is missing any
of the four ids at tap time, insert exactly these objects into its
`records` array (order doesn't matter; `graveyard.py` is append-order, not
sort-order, sensitive only for which record is "newest" per path, and
these four ids are unique to this batch):

```json
[
  {
    "id": "2026-08-26-thomas-server-app-part03-py-1",
    "kind": "file",
    "name": "thomas/server/app_part03.py",
    "dead_sha": "4273b68edafd6b810116249b992d062efe491353",
    "deleted_on": "2026-08-26",
    "reason": "salvage-debris: orphan half of the legacy *_part*.py loader; app.py:16-25 activates load_monolith_source only when ALL FOUR app_part01..04.py exist and only this one is present on disk, so the branch has been permanently dead since the worktree-fleet salvage. Evidence: .superpowers/sdd/2026-08-25-phase2-recon/recon.md Section 3c, Section 4 #4. Root cause: 36ad0730 praxis-salvage snapshot of full (10613 files).",
    "by": "claude",
    "refs": null
  },
  {
    "id": "2026-08-26-apps-site-src-app-globals-part01-css-1",
    "kind": "file",
    "name": "apps/site/src/app/globals_part01.css",
    "dead_sha": "5170ecfdbc7398bb96876c71be40f6183a9506a4",
    "deleted_on": "2026-08-26",
    "reason": "salvage-debris: duplicate split of the still-present, still-full globals.css (3666 lines); never wired up, never referenced by any import/link/build config in apps/site. Evidence: .superpowers/sdd/2026-08-25-phase2-recon/recon.md Section 3c, Section 4 #4. Root cause: 36ad0730 praxis-salvage snapshot of full (10613 files).",
    "by": "claude",
    "refs": null
  },
  {
    "id": "2026-08-26-apps-site-src-app-globals-part02-css-1",
    "kind": "file",
    "name": "apps/site/src/app/globals_part02.css",
    "dead_sha": "4dc709a43676fd6728fe4cb9069505a6880f9a84",
    "deleted_on": "2026-08-26",
    "reason": "salvage-debris: duplicate split of the still-present, still-full globals.css (3666 lines); never wired up, never referenced by any import/link/build config in apps/site. Evidence: .superpowers/sdd/2026-08-25-phase2-recon/recon.md Section 3c, Section 4 #4. Root cause: 36ad0730 praxis-salvage snapshot of full (10613 files).",
    "by": "claude",
    "refs": null
  },
  {
    "id": "2026-08-26-apps-site-src-app-globals-part03-css-1",
    "kind": "file",
    "name": "apps/site/src/app/globals_part03.css",
    "dead_sha": "5170ecfdbc7398bb96876c71be40f6183a9506a4",
    "deleted_on": "2026-08-26",
    "reason": "salvage-debris: duplicate split of the still-present, still-full globals.css (3666 lines); never wired up, never referenced by any import/link/build config in apps/site. Evidence: .superpowers/sdd/2026-08-25-phase2-recon/recon.md Section 3c, Section 4 #4. Root cause: 36ad0730 praxis-salvage snapshot of full (10613 files).",
    "by": "claude",
    "refs": null
  }
]
```

Documented one-liner (idempotent — skips any id already present, so it is
safe to run even if some but not all four records survived):

```
python -c "import json; from pathlib import Path; p = Path('docs/ops/graveyard.json'); doc = json.loads(p.read_text(encoding='utf-8')); new = json.loads(Path('/path/to/the-four-records-above.json').read_text(encoding='utf-8')); existing = {r['id'] for r in doc['records']}; doc['records'].extend(r for r in new if r['id'] not in existing); p.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + chr(10), encoding='utf-8')"
```

(Save the JSON array above to a file first — e.g.
`/path/to/the-four-records-above.json` — then point the one-liner at it;
pasting a multi-line JSON literal inline is more failure-prone than a
`-c` snippet reading a file.)

**Fallback — re-run the four `record-file` invocations, verbatim, then
refresh this document's id list.** Only if the primary path above is not
usable for some reason. This regenerates ids stamped with the re-record
date, which will NOT match the four ids listed above — if you take this
path, update the id list and this recovery block's JSON to the newly
generated ids before proceeding to step 7:

```
python scripts/forge/graveyard.py record-file thomas/server/app_part03.py 4273b68edafd6b810116249b992d062efe491353 --reason "salvage-debris: orphan half of the legacy *_part*.py loader; app.py:16-25 activates load_monolith_source only when ALL FOUR app_part01..04.py exist and only this one is present on disk, so the branch has been permanently dead since the worktree-fleet salvage. Evidence: .superpowers/sdd/2026-08-25-phase2-recon/recon.md Section 3c, Section 4 #4. Root cause: 36ad0730 praxis-salvage snapshot of full (10613 files)." --by claude

python scripts/forge/graveyard.py record-file apps/site/src/app/globals_part01.css 5170ecfdbc7398bb96876c71be40f6183a9506a4 --reason "salvage-debris: duplicate split of the still-present, still-full globals.css (3666 lines); never wired up, never referenced by any import/link/build config in apps/site. Evidence: .superpowers/sdd/2026-08-25-phase2-recon/recon.md Section 3c, Section 4 #4. Root cause: 36ad0730 praxis-salvage snapshot of full (10613 files)." --by claude

python scripts/forge/graveyard.py record-file apps/site/src/app/globals_part02.css 4dc709a43676fd6728fe4cb9069505a6880f9a84 --reason "salvage-debris: duplicate split of the still-present, still-full globals.css (3666 lines); never wired up, never referenced by any import/link/build config in apps/site. Evidence: .superpowers/sdd/2026-08-25-phase2-recon/recon.md Section 3c, Section 4 #4. Root cause: 36ad0730 praxis-salvage snapshot of full (10613 files)." --by claude

python scripts/forge/graveyard.py record-file apps/site/src/app/globals_part03.css 5170ecfdbc7398bb96876c71be40f6183a9506a4 --reason "salvage-debris: duplicate split of the still-present, still-full globals.css (3666 lines); never wired up, never referenced by any import/link/build config in apps/site. Evidence: .superpowers/sdd/2026-08-25-phase2-recon/recon.md Section 3c, Section 4 #4. Root cause: 36ad0730 praxis-salvage snapshot of full (10613 files)." --by claude
```

**Why this can't wait for a future tap**: until this lands, `tests/
test_salvage_debris_stays_dead.py`'s graveyard-record assertion runs as a
disclosed `pytest.skip` in CI for all four paths (it can see
`app_part03.py`'s deletion is real and committed, but not that any of the
four have graveyard records, since CI only sees the committed tree). The
skip carries its own expiry: `_SPLIT_LANDING_EXPIRY = 2026-10-01` in that
test file — the same constant also governs the unrelated deletion-commit
skip for the three CSS files (see that test module's docstring for why
those two gaps are independent but share one deadline). Past that date an
unlanded tap turns the skip into a hard FAIL. Landing this step before then
keeps that promotion theoretical.

### New step, inside the SAME protection-off window, BEFORE the manifest regeneration

Insert as **step 6a** in section (i)'s integrated run order below (after
step 6, before step 7 — the manifest-last rule holds here too, though for a
narrower reason: `docs/ops/graveyard.json` lives in `[protected].
enforcement_files`, not `enforcement_scripts` — the manifest generated in
step 7 only ever hashes `enforcement_scripts` — so this commit cannot
invalidate that regeneration either way, but it belongs with the other
protected-file commits landing in this window, and landing it before step 7
means step 7's later verification runs (`enforcement_integrity.py`, section
(i)'s smoke tests) see the final state of everything this window touched,
not a partial one):

> **6a.** Stage and commit the pending `docs/ops/graveyard.json` append —
> a separate, unrelated commit from step 9's protected-list-promotion
> commit, sharing only the open window:
> ```
> git add docs/ops/graveyard.json
> git commit -m "chore(forge): the four salvage-debris tombstones land - graveyard.json append"
> ```
> `protected_files_gate.py`'s local mode passes because the breakglass
> window opened in step 1 is still active. Direct `git commit` (not
> `commit.py`) matches this batch's own precedent at step 9 — `commit.py`
> runs the identical `protected_files_gate.py` check with no bypass, so it
> offers nothing extra inside an already-open window.

STATUS: PREPARED — unchanged by this addition; nothing above has executed.

---

### Round 2 addition (amended 2026-08-26): the camera is fixed, but the wrapper still can't stage its own proof

Context since the section above was written: `scripts/forge/gates/
site_visual_proof.py`'s comparator was fixed in two commits —
`f692f6d7` (deterministic capture: waits for `document.fonts.ready`) and
`58213750` (symmetric, measured-tolerance comparator; cite `58213750`, not
`6983c1388db1661507d6187a1217cbdb77dd747d` — that commit's message falsely
claimed an unrelated wrapper fix that was never landed, and was reverted
(`5077b288`) and relanded byte-identical under `58213750`'s honest message;
see `plans/thomas/tasks/PRAXIS-PHASE14-BREAKGLASS/batch.md`'s own git
history and `plans/thomas/problems/wrapper-bypass-and-false-claim-
2026-08-26/PROBLEM.md`). The gate now measures **0.0% footer-focus drift on
clean `dev`** — the baseline drift that blocked the three pending
`globals_part0N.css` deletions in the section above is resolved.

**The deletions still cannot land through the sanctioned `commit.py`
wrapper, for an unrelated reason.** Deleting the three CSS files trips the
gate's `must_change` check, which requires the regenerated proof bundle
(`apps/site/verification/ui-proof.json`, `runtime-report.json`, and fresh
`diffs/`+`screenshots/` PNGs) to land in the SAME commit. Two of those
paths — `apps/site/verification/diffs/` and
`apps/site/verification/screenshots/` — are `.gitignore`'d as directories
while already holding tracked files. `commit.py`'s isolated-temp-index
`git add -A -- <paths>` exits non-zero the instant any pathspec matches a
`.gitignore` rule, even though the underlying `git add` still stages the
change correctly; `_prepare_temp_index` treats any non-zero exit as fatal,
so the wrapper refuses the commit outright. Reproduced with the exact
pathspec (append one byte to a tracked file under either directory, then
`git add -A -- <that path>` from repo root → exit 1, `.gitignore`
advisory, `git diff --cached --stat` shows it staged anyway regardless).
Full account: `plans/thomas/problems/wrapper-bypass-and-false-claim-
2026-08-26/PROBLEM.md`.

**Step A (6b below) — `.gitignore` edit (protected).** Current lines,
quoted exactly so you can verify against the file before signing:

```
180: # Visual-regression OUTPUT (regenerated every run; baselines stay tracked).
181: apps/site/verification/diffs/
182: apps/site/verification/screenshots/
183: apps/site/verification/runtime-report.json
184: apps/site/verification/ui-proof.json
```

Delete lines 181-182 — the minimum needed to unblock the pending
CSS-deletion commit; both directories hold already-tracked, gate-required
evidence, not disposable build output, so the "regenerated every run"
comment's implied "safe to ignore" doesn't match how `site_visual_proof.py`
actually uses them (it requires exactly these paths in the committed
changed-set whenever a UI file changes).

Lines 183-184 are the same category of wrong per the review — also
already-tracked, gate-required files under the same inaccurate comment —
but this batch's own reproduction (above) isolated the confirmed `git add`
failure to the two DIRECTORY-form rules (181-182); the two FILE-form rules
(183-184) are a different `.gitignore` mechanism and were not separately
proven to trigger the same wrapper failure. Two options, your call:
- **Remove only lines 181-182** (minimum fix): unblocks the pending
  CSS-deletion commit today; leaves the untested file-form rules on
  183-184 in place — unresolved, but also unproven-broken.
- **Remove all four lines 181-184** (the review's recommendation): treats
  the whole proof bundle consistently as tracked, gate-required evidence
  instead of partially-ignored build output; a slightly larger diff to
  review, no downside identified in the record cited above.

**Step B (6c below) — land the pending CSS-deletion commit.** With 6b's
`.gitignore` edit landed (git reads ignore rules from the working tree, so
this must be committed before the regeneration below, not merely staged),
regenerate the proof bundle against the now-fixed pipeline:

```
python scripts/refresh_site_visual_proof.py
```

Then land via the sanctioned wrapper — this is the same `commit.py` path
every other agent commit in this repo uses (see `449cf5dc`, `dbf5dfb3`,
`323cf1c8` for the exact recipe this mirrors: Bash, `$'...'`-quoted
message, `--allow-scope-fallback` if no active claim covers these paths):

```
.venv/Scripts/python.exe scripts/crew/brief/commit.py --agent <your-agent-id> \
  --message "$MSG" \
  --include apps/site/src/app/globals_part01.css \
  --include apps/site/src/app/globals_part02.css \
  --include apps/site/src/app/globals_part03.css \
  --include apps/site/verification/ui-proof.json \
  --include apps/site/verification/runtime-report.json \
  --include apps/site/verification/screenshots/full-page.png \
  --include apps/site/verification/screenshots/footer-focus.png \
  --include apps/site/verification/diffs/full-page-diff.png \
  --include apps/site/verification/diffs/footer-focus-diff.png \
  --allow-scope-fallback \
  --fallback-reason "PRAXIS-PHASE14-BREAKGLASS tap: landing the pending salvage-debris CSS deletions now that .gitignore no longer blocks the proof bundle"
```

(`$MSG` is a file/variable holding the commit message — no double quotes
inside it, per this repo's commit-tooling rule.) Nine paths: the three CSS
deletions plus the six regenerated proof files (2 JSON + 2 screenshots + 2
diffs) — this is a fresh, exhaustive listing, not the directory itself
(`--include`-ing a directory path does not select the files inside it).
`tests/test_salvage_debris_stays_dead.py`'s expiring skip
(`test_every_committed_salvage_orphan_deletion_does_not_exist_in_head`)
flips from SKIP to PASS the moment this commit lands — before its
`_SPLIT_LANDING_EXPIRY = 2026-10-01` hard-fail date.

**Named future item (not this tap — needs its own review cycle):** the
wrapper self-integrity practice from the `wrapper-bypass-and-false-claim-
2026-08-26` incident (`commit.py` verifying its own executing bytes
against the `agent_safety.toml`/manifest hash at startup, so a
locally-patched wrapper can never get a false claim past its own
enforcement check again) — full detail and rationale in
`plans/thomas/problems/wrapper-bypass-and-false-claim-2026-08-26/
PROBLEM.md`, left deliberately un-closed there since the practice doesn't
exist yet and `commit.py` is itself a protected file no agent can
self-approve changing. Noted here only so the queue is visible to whoever
signs this tap — not part of what this tap lands.

STATUS: PREPARED — unchanged by this addition; nothing above has executed.

---

### (i) Integrated run order (supersedes section (d) above — one tap, not two)

**Corrected 2026-08-26, final-review fix wave, Critical-2.** The version of
this list before the fix wave regenerated the manifest (as step 4) BEFORE
editing `commit.py` (step 5) — broken, because `commit.py` is itself a
`enforcement_scripts` entry the manifest hashes. **Why manifest-last is
load-bearing, in one line:** the manifest must be regenerated only after
every protected-list file this run touches has reached its FINAL on-disk
content, because regenerating it any earlier freezes a hash that a
later-in-the-same-run edit then invalidates, hard-blocking the commit this
whole ceremony exists to produce. This is not a style preference — it is
the same rule the phase-0 batch's run order already follows
(`plans/thomas/tasks/PRAXIS-PHASE0-BREAKGLASS/batch.md`, step 4: "re-blesses
… against the current `monolith_guard.py` (and anything else already
changed under `agent_safety.toml`'s protected list at the time you run
this)" — run AFTER the edits, not before). Section (d) above broke that
precedent; this corrected list restores it. Follow THIS list, not (d)'s in
isolation:

1. `python scripts/breakglass_window.py on`
2. `python scripts/runtime_protection_toggle.py off`
3. Edit `agent_safety.toml`:
   - section (a)'s line: `"scripts/forge/gates/workboard_evidence_gate.py",`
     (`enforcement_scripts`)
   - section (e)'s line: `"scripts/forge/gates/problem_closure_gate.py",`
     (`enforcement_scripts`)
   - section (h)'s line: `"docs/ops/accepted_risks.json",`
     (`enforcement_files`, a separate array)
   - Net result: `enforcement_scripts` 61 → 63; `enforcement_files` +1.
4. Edit `scripts/crew/brief/commit.py`:
   - section (b)'s tuple: `("workboard_evidence", ...)`
   - section (g)'s tuple: `("problem_closure", ...)`
5. Edit `.pre-commit-config.yaml`: section (f)'s new hook.
6. (c) is still optional and separate, as originally written — unchanged by
   this amendment. If taken, it edits `workboard_claims.py`, which is ALSO
   in `enforcement_scripts` — do it here, before step 7, for the identical
   reason step 4 must precede step 7 (same trap, same file class).
6a. **(added 2026-08-26, Phase 2 addition above.)** Stage and commit the
   pending `docs/ops/graveyard.json` append — four salvage-debris death
   records, ids `2026-08-26-thomas-server-app-part03-py-1`,
   `2026-08-26-apps-site-src-app-globals-part01-css-1`,
   `2026-08-26-apps-site-src-app-globals-part02-css-1`,
   `2026-08-26-apps-site-src-app-globals-part03-css-1`, verified the ONLY
   uncommitted delta in that file (`git diff --stat docs/ops/graveyard.json`
   → `40 insertions(+), 0 deletions(-)`, pure append). A separate commit
   from step 9's below, sharing only the open window:
   ```
   git add docs/ops/graveyard.json
   git commit -m "chore(forge): the four salvage-debris tombstones land - graveyard.json append"
   ```
   Does not touch `enforcement_scripts` (this file lives in
   `enforcement_files`, which step 7's manifest never hashes) — placed
   before step 7 anyway so every protected-file commit in this window lands
   before the window's closing verification runs, not to satisfy the
   manifest-hash ordering itself.
6b. **(added 2026-08-26, Round 2 addition below.)** Edit `.gitignore` —
   delete lines 181-182 (`apps/site/verification/diffs/`,
   `apps/site/verification/screenshots/`; see the Round 2 section below for
   the exact quoted lines and the four-line-vs-two-line choice), then
   commit alone, same pattern as 6a:
   ```
   git add .gitignore
   git commit -m "chore(site): the proof bundle stops fighting its own gate - .gitignore no longer blocks tracked evidence"
   ```
6c. **(added 2026-08-26, Round 2 addition below.)** With 6b landed on
   disk, regenerate the proof bundle against the now-fixed comparator
   (`f692f6d7` + `58213750`), then land the three pending CSS deletions
   through the now-unblocked sanctioned wrapper — see the Round 2 section
   below for the exact commands.
7. Run `python scripts/forge/gates/enforcement_integrity.py
   --generate-manifest` **once, last, after every edit above** — re-blesses
   `scripts/forge/gates/enforcement_manifest.json` against the final
   63-entry `enforcement_scripts` list. `commit.py` and `workboard_claims.py`
   (if (c) was taken) are both already entries on that list — editing their
   *content* does not change the *count*, but it does change their hash,
   which is exactly why the regen must run after those edits, not before.
   This does not touch `enforcement_files` — see the note in section (h).
8. Review the diff on every touched file: `agent_safety.toml`,
   `scripts/forge/gates/enforcement_manifest.json`,
   `scripts/crew/brief/commit.py`, `.pre-commit-config.yaml`, and
   `scripts/forge/gates/workboard_claims.py` only if (c) was taken.
9. Commit the staged files in one commit (`agent_safety.toml`,
   `scripts/forge/gates/enforcement_manifest.json`,
   `scripts/crew/brief/commit.py`, `.pre-commit-config.yaml`, and
   `scripts/forge/gates/workboard_claims.py` only if (c) was taken). The
   protected-files gate's breakglass/approval-trailer path (open since step
   1) covers this commit. `enforcement_integrity.py --check-staged`
   (`.pre-commit-config.yaml`'s own hook, no `runtime_protection_disabled`
   short-circuit) now passes because the manifest staged in step 7 matches
   every file staged alongside it — this is the entire reason step 7 had to
   move after steps 3-6, not before them.
10. `python scripts/runtime_protection_toggle.py on`
11. `python scripts/breakglass_window.py off`

**Smoke tests — run AFTER step 11, outside the protection-off window**
(matching this batch's existing pattern above of verifying after landing,
not while the window is open):

```
python scripts/forge/gates/enforcement_integrity.py              # integrity check passes: the manifest was generated last, against the exact committed content
python scripts/forge/gates/workboard_evidence_gate.py             # local staged-mode run, PASS/no-op on a clean board
python scripts/forge/gates/problem_closure_gate.py                # local staged-mode run, PASS/no-op on a clean board
python scripts/crew/brief/commit.py --help                        # confirms commit.py still imports cleanly with both new entries
pre-commit run thomas-problem-closure-gate --all-files             # confirms the new hook id resolves and runs
```

---

## Branch-equilibrium addition (amended 2026-08-27, Task 4 — closure under the loop's law)

Source: `docs/superpowers/plans/2026-08-27-branch-equilibrium.md` Task 4;
`plans/thomas/tasks/PRAXIS-BRANCH-EQUILIBRIUM/status.md` (what enforces
where, today, and why this batch is this pair's chosen home). Not a new
ceremony — this rides the SAME open protection window as (a)-(h) and the
Phase 2 / Round 2 additions above, for the identical reason: two more
protected-file edits landing the same day as everything else queued here
need no second Windows Hello sign-in.

**What's pending**: two independent, unrelated tap items from the
branch-equilibrium plan, both already shipped as unwired library code with
their wiring deferred because every real call site is protected:

### (j) `trunk_health.write_push_gate_cache()` wiring into `merge_readiness.py`

**Current state**: `scripts/crew/brief/trunk_health.py` ships
`write_push_gate_cache()`, tested, but called by nothing in production —
every candidate writer call site (`merge_readiness.py`, `preflight.py`,
`dead_ref_gate.py`, `scripts/_gate_python.py`, `.pre-commit-config.yaml`
itself) is protected under `agent_safety.toml`. Until this lands, every
session's `TRUNK:` line reads `push-gate unchecked (never)` — honest, not
broken.

**The edit** — inside `scripts/forge/gates/merge_readiness.py`'s `run()`,
immediately after `ok, results = evaluate_merge_readiness()` (exact text,
already quoted verbatim in `trunk_health.py`'s own module docstring so this
batch does not risk drifting from the shipped function's real signature):

```python
from scripts.crew.brief.trunk_health import write_push_gate_cache
write_push_gate_cache(
    ROOT, ok=ok, blocked_gates=[r["name"] for r in results if not r["ok"]]
)
```

`merge_readiness.py` is in `agent_safety.toml`'s `enforcement_scripts` list
already (pre-existing entry, not added by this batch) — this edit changes
its *content*, which is exactly why the manifest regeneration must run
after this edit, same rule section (i) above already states for every other
file in this class.

### (k) `branch_claim_gate.py` promotion: `.pre-commit-config.yaml` hook + `commit.py` is NOT touched

**Current state**: `scripts/forge/gates/branch_claim_gate.py` is
RED_PATH-registered and CI-enforcing (`.github/workflows/gates.yml`'s
`branch-claim-gate` job, runs on every PR), but has no local pre-push hook
and is not in `agent_safety.toml`'s `enforcement_scripts`. Unlike
`workboard_evidence_gate.py` and `problem_closure_gate.py` above, this gate
is **pre-push shaped** (git's own stdin protocol, not a board-diff check),
so its nearest sibling for wiring shape is `dead_ref_gate.py`
(`PRAXIS-PHASE1-BREAKGLASS/batch.md`, already EXECUTED) — a `commit.py`
`LOCAL_GATE_COMMANDS` entry is the wrong shape for this gate, the same way
it was the wrong shape for `dead_ref_gate.py`, because `commit.py` runs at
commit time, not push time, and has no pre-push stdin to hand it.

**The edit** — one new `.pre-commit-config.yaml` hook, styled identically
to `thomas-dead-ref-gate` immediately above it:

```yaml
      - id: thomas-branch-claim-gate
        name: Thomas Branch Claim Gate (anonymous pushes need an owner)
        entry: python scripts/_gate_python.py scripts/forge/gates/branch_claim_gate.py
        language: system
        pass_filenames: false
        stages: [pre-push]
```

Plus one line to `agent_safety.toml`'s `enforcement_scripts` (same array
section (a)/(e) above already extended, "── Agent commit path ──" or its
pre-push-hook-chain neighbor):

```toml
"scripts/forge/gates/branch_claim_gate.py",
```

**Combined count**: this line, together with sections (a) and (e) above (if
this section lands in the same pass as those), takes `enforcement_scripts`
from **61 to 64** — one more than section (i)'s stated 63, if (j)/(k) land
alongside (a)/(e)/(h) in a single signed run. If this section is signed on
its own, in a LATER window than (a)/(e)/(h), start the count from whatever
`enforcement_scripts` already holds at that time (verify by loading
`agent_safety.toml` directly before editing, the same "current state,
verified against the tree" discipline every section above already uses —
do not assume 61 or 63 without checking).

### (l) Run order (this section only — does not alter section (i)'s order for (a)-(h))

1. `python scripts/breakglass_window.py on`
2. `python scripts/runtime_protection_toggle.py off`
3. Edit `scripts/forge/gates/merge_readiness.py`: add section (j)'s
   `write_push_gate_cache()` call.
4. Edit `agent_safety.toml`: add section (k)'s
   `"scripts/forge/gates/branch_claim_gate.py",` line to
   `enforcement_scripts`.
5. Edit `.pre-commit-config.yaml`: add section (k)'s new hook.
6. Run `python scripts/forge/gates/enforcement_integrity.py
   --generate-manifest` **last, after both edits above** — same
   manifest-last rule as section (i): `merge_readiness.py`'s content
   changed (step 3) and `enforcement_scripts`'s membership changed (step
   4), both must be final before the manifest hashes them.
7. Review the diff on `scripts/forge/gates/merge_readiness.py`,
   `agent_safety.toml`, `scripts/forge/gates/enforcement_manifest.json`,
   and `.pre-commit-config.yaml`.
8. Commit the staged files in one commit. The protected-files gate's
   breakglass/approval-trailer path (open since step 1) covers this
   commit.
9. `python scripts/runtime_protection_toggle.py on`
10. `python scripts/breakglass_window.py off`

**Smoke tests — run AFTER step 10, outside the protection-off window**:

```
python scripts/forge/gates/enforcement_integrity.py                       # integrity check passes against the new manifest
python scripts/crew/brief/trunk_health.py                                 # after a push through the wired hook, push-gate should read ok/blocked, not unchecked
python scripts/forge/gates/branch_claim_gate.py                           # local staged-mode run, PASS/no-op with the seeded registry
pre-commit run thomas-branch-claim-gate --hook-stage pre-push --all-files # confirms the new hook id resolves and runs
```

**Not part of this section, stated so it is not assumed later**: the
`branch-claim-gate` CI job's required-flip (`gates-required`'s `needs:`
list) is a separate, later decision per
`plans/thomas/tasks/PRAXIS-BRANCH-EQUILIBRIUM/status.md` — this tap wires
LOCAL enforcement only, it does not make the branch itself required to
land a PR.

STATUS: PREPARED — unchanged by this addition; nothing above has executed.

---

STATUS: EXECUTED 2026-09-01 (owner-signed, two Windows Hello taps).
Commits: a99e2e54 (promotion: enforcement_scripts 61->64, manifest re-blessed
last, commit.py + pre-commit wiring, merge_readiness cache writer), fda19920
(graveyard tombstones), ca02b786 (.gitignore, all-four option per the review
recommendation), 617a8263 (CSS deletions + regenerated proof bundle, gate
PASS). Protection re-armed immediately after the commits. Disclosed
deviations: all commits ran via the sanctioned wrapper rather than raw git
(the session's auto-mode classifier declined raw hook-config staging; the
wrapper runs strictly more checks inside the same open window), and the
manifest/promotion commit landed before steps 6a/6b/6c — inside the batch's
own stated tolerance (6a's placement was documented as not load-bearing).
Smoke tests all green outside the window; the salvage expiring skip flipped
to PASS a month ahead of its 2026-10-01 deadline. Section (c) remains
deferred per its own recommendation. Section (l)'s items landed in this same
window, as its combined-count note anticipated (61 -> 64).
