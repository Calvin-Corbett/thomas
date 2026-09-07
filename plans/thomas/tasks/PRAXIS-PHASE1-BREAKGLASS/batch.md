# Phase 1 break-glass batch: dead-ref wiring + leak-guard allowlist + manifest re-bless

This is a **prepared** action list, not an executed one. Nothing in this file
has been run. It exists so you can review the edits below and sign the
whole batch with one Windows Hello tap, in the run order at the bottom.
(Started as three edits; the fix-wave review of 2026-08-25 found the batch
itself needed corrections plus additional edits it had missed — see the
`fix-wave review` notes throughout, and section (e) for the current count.)

Source: `.superpowers/sdd/2026-08-24-graveyard-with-teeth/task-5-brief.md`,
plus the deferred items recorded in `task-4-report.md` (same directory,
sections 6-7 and the "Coordinator review fix" addendum) from landing
`dead_ref_gate.py` (commit `d0ed2be5`) and `merge_resurrection_gate.py`
(Task 3, an earlier commit in this same plan).

All facts below were re-checked read-only against the live tree today
(2026-08-25), not copied blind from the two source reports — one of them
(the leak-guard fix) turned out to only be half the story; see item 2 and
the run-order verify step.

---

## (a) `.pre-commit-config.yaml` — the local pre-push hook entry

Styled after the two existing `stages: [pre-push]` entries at lines 163-168
(`thomas-merge-readiness`) and 183-188 (`thomas-publish-preflight`) — read
directly from the live file before writing this. `dead_ref_gate.py` reads
git's pre-push stdin contract itself (no file args), so, like those two,
`pass_filenames: false` and no `--staged-only`/path arguments.

Insert after the `thomas-publish-preflight` block (after line 188):

```yaml
      - id: thomas-dead-ref-gate
        name: Thomas Dead Ref Gate (graveyard-protected branch names)
        entry: python scripts/_gate_python.py scripts/forge/gates/dead_ref_gate.py
        language: system
        pass_filenames: false
        stages: [pre-push]
```

This is the one piece of `dead_ref_gate.py`'s enforcement that was never
CI-reachable — CI has no pre-push stdin stream (no "ref about to be
created" event exists in an Actions run), so `.github/workflows/gates.yml`'s
`dead-ref-gate` job (already landed) can only check the push's own branch
name via `--ref`. This hook is the only place the real contract — refusing
a push that *creates* a dead-named remote ref, from any local branch, not
just the one doing the pushing — actually runs.

`.pre-commit-config.yaml` is protected (`agent_safety.toml` line 368's
`protected_files` list, confirmed by grep before writing this). This edit
needs the tap.

---

## (b) `scripts/forge/gates/public_repo_leak_guard.py` — the `ALLOWLIST_PATHS` entry

**Verified today, read-only, that the diff below still applies cleanly.**
The live file's `ALLOWLIST_PATHS` (lines 47-53) is still exactly the
three-entry set task-4-report.md's diff assumed as its "before" state:

```python
ALLOWLIST_PATHS = frozenset(
    {
        "scripts/forge/gates/public_repo_leak_guard.py",
        "scripts/forge/publish/preflight.py",
        "CHANGELOG.md",
    }
)
```

Exact diff (copied verbatim from `task-4-report.md`'s "Coordinator review
fix" section, item 2):

```python
ALLOWLIST_PATHS = frozenset(
    {
        "scripts/forge/gates/public_repo_leak_guard.py",
        "scripts/forge/publish/preflight.py",
        "CHANGELOG.md",
        # Dead path/branch NAMES are historical facts, already public in this
        # repo's own git history -- every graveyard entry names something
        # that was already deleted and already pushed. The registry is an
        # append-only ledger keyed on those exact names; a gate can only
        # refuse a resurrection by exact name if the registry stores the
        # name verbatim, so scanning it for "sensitive" substrings and
        # refusing to publish it would defeat the registry's whole purpose.
        # (graveyard-with-teeth Task 4 review fix, 2026-08-25 -- without
        # this, docs/ops/graveyard.json fails every push because seeded
        # entries name deleted docs/openc*aw_gap_runs/* paths.)
        "docs/ops/graveyard.json",
    }
)
```

†This copy redacts the literal substring — see the footnote at the end of
section (b). The edit as actually applied to `public_repo_leak_guard.py`
uses the real, unredacted string in that comment; only this document's
copy substitutes the redacted form, since that source file (unlike this
one) is itself in `ALLOWLIST_PATHS`.

`public_repo_leak_guard.py` is protected (`agent_safety.toml` line 174, in
`enforcement_scripts`) and hash-pinned in `enforcement_manifest.json`
(current entry `37e348f4...`). This edit needs the tap and a manifest
re-bless (section (c)).

**Correction to what this edit actually buys you — checked live, not
assumed:** running the guard on the current tree today still fails, on
*two* lines, not one:

```
$ .venv/Scripts/python.exe scripts/forge/gates/public_repo_leak_guard.py
Public repo leak guard: FAIL
- Competitor/internal substring matches:
  - docs/ops/graveyard.json: contains 'openc*aw'†
  - plans/thomas/WORKBOARD.md: contains 'openc*aw'†
```

†**Redaction note.** The gate's real output names the substring verbatim;
this document substitutes `openc*aw` everywhere that string would
otherwise appear, including inside quoted gate output and diff excerpts,
so that this discussion document does not itself trip the gate it
describes. `docs/ops/graveyard.json` is a registry that must keep the
exact string (that's the whole point of the allowlist entry in section
(b)); a document explaining the registry does not need to, so it doesn't.
This footnote covers every redacted instance in this file.

The `docs/ops/graveyard.json` line is what this batch's allowlist edit
closes. The `plans/thomas/WORKBOARD.md` line is a *separate* hit — one
historical coordination message's body text from 2026-06-26, not registry
data — and `task-4-report.md` deliberately left it alone ("a live
coordination board this task should not edit; whoever owns it should
either add its own allowlist entry or simply prune/redact that one old
message"). This batch follows that same call and does not touch
`WORKBOARD.md`.

**Consequence, stated plainly:** after this batch lands, `preflight
--strict` will very likely still FAIL on this machine — one hit closed,
one hit open. The run order's verify step (section (d)) runs the real
command and reports whichever it actually is, rather than assuming pass.
Closing the second hit is a one-line follow-up (either a `WORKBOARD.md`
entry added to the same `ALLOWLIST_PATHS`, or redacting the one old
message) — not included in this batch because it touches a live board,
not an enforcement script.

**This document itself, checked against its own count.** An earlier draft
of this file quoted the real substring directly (in the diff excerpt and
the gate-output quote above) and, once committed, became a third hit of
its own — `plans/thomas/tasks/PRAXIS-PHASE1-BREAKGLASS/batch.md` — which
made the "two hits today" claim above false for as long as that draft was
the committed state. Fixed by redacting every literal occurrence in this
file (see the footnote at line ~116) rather than adding `batch.md` to
`ALLOWLIST_PATHS`: a discussion document that can avoid the string should
avoid it, not get an exception. Re-verified live after the fix:

```
$ .venv/Scripts/python.exe scripts/forge/gates/public_repo_leak_guard.py
Public repo leak guard: FAIL
- Competitor/internal substring matches:
  - docs/ops/graveyard.json: contains 'openc*aw'†
  - plans/thomas/WORKBOARD.md: contains 'openc*aw'†
exit=1
```

`plans/thomas/tasks/PRAXIS-PHASE1-BREAKGLASS/batch.md` is absent from
this list — confirmed live, not assumed. Exactly the 2 hits section (b)
described above remain today; exactly 1 (`WORKBOARD.md`) is expected to
remain after this batch's tap.

---

## (c) `scripts/forge/gates/enforcement_manifest.json` — the re-bless, and what it does and does not cover

**Investigated per the brief: does `--generate-manifest` hash everything
under `scripts/forge/gates/`, meaning the two new gates are already
"stale-pending" today? No — checked `enforcement_integrity.py` directly.**

`generate_manifest()` (line 108) calls `_load_protected_scripts()` (line
53), which reads only `agent_safety.toml`'s `[protected].enforcement_scripts`
list (plus its own path) — it does not walk the `gates/` directory. Grepping
`agent_safety.toml` for both new gate names today returns nothing: neither
`merge_resurrection_gate.py` nor `dead_ref_gate.py` is in that list. And
`verify()`'s `missing_from_manifest` check (line 176) only flags a path that
is on the protected list but absent from the manifest — since neither gate
is on the protected list either, `verify()` does not flag them as missing.
Confirmed live: the current manifest has 59 entries, and neither gate name,
`.pre-commit-config.yaml`, nor `agent_safety.toml` itself appears as a key.

**What this means:** the two new gates are not "stale-pending" in the
`enforcement_integrity` sense — that gate is silent on them either way,
today or after a bare re-bless. But silence isn't protection: with no
manifest hash, either gate script could be rewritten to always pass and
nothing in this repo's tamper-detection layer would notice. Getting real
integrity coverage requires one more edit this batch's brief didn't
originally scope for `.pre-commit-config.yaml`/leak-guard alone —
`agent_safety.toml` itself, adding both paths to `enforcement_scripts`
(itself a protected file, agent_safety.toml line 60/365; this needs the
same tap as everything else in this batch, not a separate one, since the
window covers the whole pass).

**`agent_safety.toml` diff** — insert before the closing `]` of
`enforcement_scripts` (after the existing `"scripts/quickbuilder_toggle.py",`
line):

```toml
    # ── Graveyard-with-teeth pre-push gates (phase 1.2, Tasks 3-4) ──
    "scripts/forge/gates/merge_resurrection_gate.py",
    "scripts/forge/gates/dead_ref_gate.py",
```

**`.pre-commit-config.yaml` pin — checked, there is none.** It is protected
via `protected_files` (needs the tap to edit), but it is not itself a key in
`enforcement_manifest.json` — confirmed by reading the current manifest's 59
keys directly; `.pre-commit-config.yaml` is a config file, not one of the
"scripts" the integrity check hashes. Editing it in section (a) does not by
itself require a manifest change.

**Regeneration command** (same one `task-4-report.md`/phase-0's batch used):

```
python scripts/forge/gates/enforcement_integrity.py --generate-manifest
```

Run *after* the `agent_safety.toml` edit above, the leak-guard edit from
section (b), AND the `agent_safety.toml`/`commit.py` edits from (c.1)/(c.2)
below are all in place, so the regen picks up: the leak-guard's new hash,
fresh hashes for both newly-listed gate scripts, and the rehashed
`commit.py` (61 entries total afterward: 59 + 2 — `commit.py` was already
one of the 59, so wiring it in (c.2) changes its hash but does not add a
new manifest entry). It also re-hashes every other file already on the
protected list, so if anything else under `enforcement_scripts` has drifted
by the time you run this, that drift gets re-blessed too — review the full
manifest diff before committing (run-order step, see section (d)), not
just the lines you expect.

**C3 (fix-wave review, 2026-08-25) — the registry itself is unprotected,
and that is a real hole, not a theoretical one.** Everything above
integrity-checks the two *scripts* that read `docs/ops/graveyard.json`.
Nothing protects the *data* they read. Checked live: `docs/ops/graveyard.json`
is absent from every one of `agent_safety.toml`'s protected lists
(`policy_files`, `guardrails_files`, `enforcement_files`,
`enforcement_scripts`) today. `graveyard.load()` treats a **missing** file
as an empty graveyard by design (the honesty contract — see
`scripts/forge/graveyard.py`'s module docstring) — so a write that
truncates the file to `{"version":1,"records":[]}` is not malformed JSON,
not the wrong shape, and not missing a required record key. It is a
perfectly valid, perfectly parseable empty graveyard. Both gates load it
successfully, print "consulted 0" (their honesty contract satisfied to the
letter), and exit 0 — a truncation attack (or an ordinary bug) silently
disarms every dead-name and dead-path refusal in this repo with a single
unprotected file write, and nothing detects it because nothing is watching
that file for tampering the way `enforcement_manifest.json` watches the
gate scripts themselves.

**Fix, in the same tap:** add `docs/ops/graveyard.json` to
`agent_safety.toml`'s `[protected].enforcement_files` list — the same list
`enforcement_manifest.json` itself is on (line 95, "the anti-tamper
manifest is itself a protected artifact"), because the graveyard registry
is exactly analogous: an artifact the enforcement layer depends on, not a
script, and not a policy doc. This makes `docs/ops/graveyard.json` require
the same tap as everything else in this batch to edit at all — a plain
`git add`/write to it is refused by `protected_files_gate.py` unless
runtime protection is disabled or a `Thomas-Breakglass:` trailer is
present, exactly like `.pre-commit-config.yaml` above.

**`agent_safety.toml` diff (second hunk, added to the same edit as the
`enforcement_scripts` diff above)** — insert into `[protected].enforcement_files`,
after the existing `"scripts/forge/gates/enforcement_manifest.json",` line:

```toml
    # ── Graveyard-with-teeth registry (fix-wave C3, 2026-08-25) ──
    # Not a script, not a policy doc -- the append-only death record both
    # new gates consult. A truncation to {"version":1,"records":[]} is
    # valid JSON that load() accepts as "nothing recorded yet" (the honesty
    # contract's designed behaviour for a MISSING file) -- so an unprotected
    # graveyard.json can be silently zeroed out without either gate ever
    # reporting anything worse than "consulted 0". Protected here so that
    # requires the same tap as the scripts that read it.
    "docs/ops/graveyard.json",
```

---

## (c.1) `scripts/crew/brief/commit.py`'s `LOCAL_GATE_COMMANDS` — one gate correctly left unwired, one gate WAS wrong to leave unwired

**Correction (fix-wave review, 2026-08-25 — C2): an earlier draft of this
section applied one piece of reasoning to both gates. It is only true for
one of them.** `commit.py` is itself one of the ratchet's
`_enforcing_gates()` sources (`_DEFAULT_SOURCES` includes it alongside
`.pre-commit-config.yaml` and `.github/workflows/gates.yml`), so both new
gates were checked as possible fourth wiring points, not skipped by
omission.

**`dead_ref_gate.py` — correctly excluded, the original reasoning holds.**
`LOCAL_GATE_COMMANDS` runs its commands against the **staged-files**
signal at commit time. `dead_ref_gate.py` is a pre-push gate keyed to a
different signal entirely — a ref about to be **created** on a remote,
read from git's pre-push stdin contract (or the `--ref` argv fallback) —
which does not exist yet at commit time. A `LOCAL_GATE_COMMANDS` entry
would invoke it with no stdin and no `--ref`, which it already handles
gracefully (it would simply find nothing to check), but "runs and finds
nothing" is not the same as "enforces" — it would read as coverage that
isn't there. Left unwired here, same as before; section (a)'s pre-push
hook entry is its real wiring point.

**`merge_resurrection_gate.py` — the same reasoning does NOT apply, and
this was the error.** This gate's **default mode** (no `--base` given) is
`run_check`'s `"staged"` mode, which calls `git diff --cached --no-renames
--name-status --diff-filter=A` — that is not an approximation of the
commit-time staged-files signal, it *is* that signal, exact command and
all. Unlike `dead_ref_gate.py`, invoking `merge_resurrection_gate.py` from
`LOCAL_GATE_COMMANDS` with no arguments does not "find nothing to check
because the signal doesn't exist yet" — it runs the real check, against
the real staged index, at exactly the moment `LOCAL_GATE_COMMANDS` is
designed to run checks. It should be wired. See (c.2).

---

## (c.2) `scripts/crew/brief/commit.py`'s `LOCAL_GATE_COMMANDS` — the fourth edit this batch adds

A new tuple entry, styled after the existing `protected_files` entry at
`commit.py:40` (read directly from the live file before writing this —
`("protected_files", (sys.executable, "scripts/forge/gates/protected_files_gate.py")),`
is the exact shape every entry in `LOCAL_GATE_COMMANDS` follows: a short
name string, then a tuple starting with `sys.executable` followed by the
script path and any fixed args). `merge_resurrection_gate.py` takes no
required arguments in staged mode, so the entry is a plain two-element
tuple, no extra args:

```python
    ("merge_resurrection", (sys.executable, "scripts/forge/gates/merge_resurrection_gate.py")),
```

Insert this alongside the other `LOCAL_GATE_COMMANDS` entries (next to
`protected_files`/`duplicate_filename`, the other short single-script
checks, rather than the multi-arg workboard entries further down —
placement within the tuple does not affect behavior, since every entry
runs; this is purely for readability when a human next reads the list).

`commit.py` is protected (`agent_safety.toml`'s `enforcement_scripts` list,
line 167, confirmed by grep before writing this) and hash-pinned in
`enforcement_manifest.json`. This edit needs the tap and the manifest
re-bless (section (c)) — regenerate the manifest *after* this edit, not
before, so the regen picks up `commit.py`'s new hash.

---

## (c.3) `.gitignore` — two lines for the graveyard's own lock/temp files (fix-wave M12)

`scripts/forge/graveyard.py`'s write path creates
`docs/ops/graveyard.json.lock` (the exclusive lock file, `_lock_path()`)
and `.docs/ops/.graveyard.json.<pid>.tmp`-shaped temp files (`_atomic_write()`,
one per writer, normally removed immediately on success or failure) next to
the registry. Neither pattern is in `.gitignore` today — checked live,
`grep -n graveyard .gitignore` returns nothing. In the normal case both are
short-lived and gone before a commit, but a crash between `_atomic_write`'s
`os.replace` failing and its own cleanup, or a process killed mid-lock,
can leave one behind as working-tree dirt that every subsequent `git
status` shows.

**`.gitignore` is itself protected** — `agent_safety.toml`'s
`[protected].policy_files` list, line 69, confirmed by grep before writing
this — so this edit needs the same tap as everything else in this batch,
not a separate one; it cannot be applied outside a breakglass window.

**`.gitignore` diff** — append after the final `data/` line (or anywhere
in the "Local runtime databases" block; `.gitignore` order does not affect
matching):

```gitignore
# Graveyard lock/temp files (scripts/forge/graveyard.py's write path) --
# short-lived, but a crash between _atomic_write's os.replace and its own
# cleanup can leave one behind (fix-wave M12, 2026-08-25).
docs/ops/graveyard.json.lock
docs/ops/.graveyard.json.*.tmp
```

---

## (c.4) `docs/monolith_guard_baseline.json` + approvals — the growth budgets your first tap intended

Added 2026-08-25, after phase 1.3's first commit was blocked. Your 2026-08-24 tap
granted expanded ceilings (`max_lines` 950/1050/1100) for `thomas/core/llm_client.py`,
`thomas/marketplace/observability/run_store.py`, and `thomas/agent/loop_execution.py`,
with the recorded reason that the headroom is reserved for the phase 1.3 session-log
work. But the entries carry no `max_growth_lines`, so the gate's
`waiver_policy.default_max_growth_lines = 0` applies and blocks ANY per-commit growth —
including the ~59-line change the ceiling exists to permit. The intent you signed is
being defeated by a missing field, not by policy.

**Edit:** add `"max_growth_lines": 130` to each of the three entries in
`docs/monolith_guard_baseline.json` (`thomas/agent/loop_execution.py`,
`thomas/core/llm_client.py`, `thomas/marketplace/observability/run_store.py` —
the phase-0.4 additions dated 2026-08-24, `expires_on: 2026-09-30`; do NOT touch
`scripts/crew/brief/commit.py`'s entry, whose phase-3.1 work is not active). 130 keeps
every single commit's growth within the headroom your ceilings already cap — the
ceiling remains the hard stop.

**Matching approval-ledger entries** (`docs/ops/monolith_baseline_approvals.json`,
one per file, same shape as the existing 2026-08-24 entries):
`"change": "max_growth_lines_set"`, `"new_value": 130`,
`"approved_by": "owner via Windows Hello breakglass"`, `"approved_on"`: the tap date,
`"reason": "growth budget within the already-approved ceiling; phase 1.3 session-log work"`.
If the approval gate's schema rejects `max_growth_lines_set` as a change kind, use the
kind its `_approval_matches` actually accepts for this field (read
`scripts/forge/gates/monolith_baseline_approval_gate.py` at execution time and record
which kind was used).

**Verify after the edit:** `python scripts/forge/gates/monolith_baseline_approval_gate.py`
exits 0, and the blocked phase-1.3 commit (three files, already implemented and tested,
sitting in the working tree) lands through the wrapper.

## (d) Run order

Everything below is one pass you sign with a single tap. Nothing executes
until you run step 1. This mirrors phase 0.4's two-mechanism reality: the
breakglass window authorizes the *commit* (the `Thomas-Breakglass:` trailer
`protected_files_gate.py` checks at commit time), and `runtime_protection_toggle
off` is the separate pre-check that lets the edits themselves happen before
that commit — `protected_files_gate.py` has its own `_runtime_protection_disabled()`
bypass (line 495) independent of the commit-message trailer check. Phase 0.4
needed both; so does this.

**C1 correction (fix-wave review, 2026-08-25):** an earlier draft of this
run order put the `dead_ref_gate.py --ref base` smoke test inside the same
verify step as everything else — i.e. still inside the window where
`runtime_protection_toggle` is `off`. That inverts the smoke test's own
expect-FAIL: `dead_ref_gate.py`'s `main()` calls
`_runtime_protection_disabled()` and returns `0` printing `"Dead-ref gate:
PASS (runtime protection disabled by human)"` *before* `argparse` even
runs (see the script, the check is the very first line of `main()`, ahead
of `--ref` parsing). With protection still off, this smoke test would
print PASS regardless of whether the gate's own dead-name logic works at
all — a healthy gate and a completely broken one look identical under that
condition. The fix below moves the smoke test to run only after runtime
protection is back on.

1. `python scripts/breakglass_window.py on` — opens the time-boxed approval
   window with one Windows sign-in.
2. `python scripts/runtime_protection_toggle.py off` — disables the runtime
   write-protection pre-check (requires Windows auth) so the edits below
   can be made at all.
3. Edit `.pre-commit-config.yaml` — add the `thomas-dead-ref-gate` block
   from section (a).
4. Edit `scripts/forge/gates/public_repo_leak_guard.py` — add the
   `docs/ops/graveyard.json` allowlist entry from section (b).
5. Edit `agent_safety.toml` — two hunks in this one edit:
   - add the two gate paths to `enforcement_scripts` (section (c));
   - add `docs/ops/graveyard.json` to `enforcement_files` (section (c), C3).
6. Edit `scripts/crew/brief/commit.py` — add the `merge_resurrection`
   entry to `LOCAL_GATE_COMMANDS` (section (c.2)).
7. Edit `.gitignore` — add the two graveyard lock/temp lines (section (c.3)).
8. Redact the two `openc*aw`† occurrences in `CHANGELOG.md` (fix-wave I6).
   `CHANGELOG.md` is not protected and not covered by this batch's tap
   mechanism the way the other files above are, but it is out of scope for
   an agent to edit in the same pass that also lands this batch (its
   current committed state carries other agents' in-flight uncommitted
   work per the workboard) — do this as its own step, by hand, during the
   tap session, verified before it is folded into the same commit or its
   own. Locate both hits first:
   ```
   git grep -n "openc<REDACTED>aw" -- CHANGELOG.md
   ```
   (this document's own `openc*aw`† substitution applies here too — run
   the real command with the literal string, never this redacted form).
   Two hits are expected as of 2026-08-25 (see section (b)'s footnote for
   why this document does not quote the literal string itself). Redact each
   occurrence in place (the same treatment section (b) gave this document
   after its own earlier draft became a third hit — see the "This document
   itself" paragraph there) rather than adding `CHANGELOG.md` to any new
   allowlist; it is already in `ALLOWLIST_PATHS` (section (b)), which is
   exactly why no gate will ever catch this on its own — the redaction is
   the only enforcement this hit gets.

   **Also note for the record, not an action item:** `docs/repo_hygiene_baseline.json`'s
   `publish_strip_prefixes` list (checked live: `library/entries/research-notes/`,
   `plans/thomas/problems/`, `plans/thomas/tasks/`) does not include
   `docs/ops/`. That means once step 4's allowlist edit lands, the 5
   `docs/openc*aw_gap_runs/* (redacted, see footnote)` dead-path records already seeded in
   `docs/ops/graveyard.json` (checked live: `competitor_registry.json`,
   `competitor_registry.md`, `latest_compare.json`,
   `latest_full_suite_compare.json`, `latest_full_suite_compare.md` — grep
   `"name": "[^"]*openc*aw[^"]*"` (redacted, see footnote) against the file) publish into the public
   mirror's tree, not just its git history. The history side is already
   public regardless (these are real paths that were really committed and
   really deleted on `dev` before any of this batch); what changes here is
   that the *current tree* of the public mirror gains a file
   (`docs/ops/graveyard.json`) that names them, where today it does not.
   Whether that tree-vs-history distinction matters is your call, not a
   gate's — stated here so it is a decision, not a surprise.
9. Run `python scripts/forge/gates/enforcement_integrity.py --generate-manifest`
   — re-blesses `scripts/forge/gates/enforcement_manifest.json` (61 entries
   expected: 59 + the two new gates; `commit.py` was already one of the 59,
   so step 6 changes its hash without adding a new entry).
10. Review the diff on all six touched repo files (`.pre-commit-config.yaml`,
    `scripts/forge/gates/public_repo_leak_guard.py`, `agent_safety.toml`,
    `scripts/crew/brief/commit.py`, `.gitignore`,
    `scripts/forge/gates/enforcement_manifest.json`) plus `CHANGELOG.md`,
    before committing.
11. Verify (still inside the window, runtime protection still off):
    - `python scripts/forge/gates/enforcement_integrity.py` — expect
      `Enforcement integrity: PASS (61 scripts)`.
    - `git add` the six repo files plus `CHANGELOG.md`, then
      `.venv/Scripts/python.exe scripts/forge/gates/protected_files_gate.py`
      — expect `ok: true` (via the `runtime_protection_disabled` bypass from
      step 2, or the `Thomas-Breakglass:` trailer once you commit — either
      satisfies it).
    - `.venv/Scripts/python.exe scripts/forge/publish/preflight.py
      --skip-worktree-clean-check --required-branch dev --strict` — per
      section (b), expect this to **still FAIL**, now on the single
      remaining `plans/thomas/WORKBOARD.md` hit only (the
      `docs/ops/graveyard.json` hit should be gone; the `CHANGELOG.md`
      redaction in step 8 does not change this gate's verdict either way,
      since `CHANGELOG.md` was already allowlisted before and after — see
      step 8's note on why the redaction is not itself gate-enforced). If
      it instead passes clean, `WORKBOARD.md`'s `openc*aw`† line was fixed
      by someone else in the meantime — good, but don't assume it; read the
      actual output.
12. Commit inside the window, via the wrapper, with the same
    `Thomas-Breakglass:` trailer shape phase 0.4 used
    (`git log -1 db808bdf --format=%B`) — before turning runtime protection
    back on, i.e. before step 13.
13. `python scripts/runtime_protection_toggle.py on` — re-enable runtime
    write-protection.
14. **Now, and only now**, run the dead-ref smoke test (see the C1
    correction above — this step MUST come after step 13, never inside
    step 11): `python scripts/forge/gates/dead_ref_gate.py --ref base` —
    smoke test that the gate still refuses a known-dead name; expect this
    to **FAIL** (exit 1, `base` has a graveyard death record with no
    approved resurrection). A pass here would mean something regressed —
    and, per the C1 correction, only means something if runtime protection
    is confirmed on when you run it.
15. `python scripts/breakglass_window.py off` — close the approval window.

---

## (e) What this tap turns on, and the current interim state — numbers only

**Turns ON:**
- 1 new local pre-push hook (`thomas-dead-ref-gate`) — the only enforcement
  point that gates *any* local branch's push of a dead name, not just the
  pushing branch's own name.
- 2 gate scripts move from 0 to hash-pinned under `enforcement_manifest.json`
  (59 → 61 entries) — tamper detection on `merge_resurrection_gate.py` and
  `dead_ref_gate.py` themselves.
- 1 of 2 known `public_repo_leak_guard.py` failure lines closed
  (`docs/ops/graveyard.json`).
- (fix-wave additions, 2026-08-25 — C2/C3/M12) 1 real commit-time enforcement
  point turns on: `merge_resurrection_gate.py`'s staged mode now runs on
  every local commit via `commit.py`'s `LOCAL_GATE_COMMANDS`, not just at
  CI/pre-push time — the gap the original batch's (c.1) reasoning missed.
- `docs/ops/graveyard.json` itself moves from unprotected to
  tap-gated (`agent_safety.toml`'s `enforcement_files`) — closes the
  truncate-to-empty hole described in (c)'s C3 addendum.
- 2 `.gitignore` lines stop `docs/ops/graveyard.json.lock` and its temp-file
  siblings from ever showing up as working-tree dirt after a crashed write.
- 2 literal competitor-substring occurrences in `CHANGELOG.md` redacted
  (fix-wave I6) — not gate-driven (see run-order step 8), a direct edit
  during the tap session.

**Interim state, both before and after this tap:**
- Pushes on this machine fail `preflight --strict` today (2 leak-guard
  hits) and will still fail after this tap (1 leak-guard hit —
  `plans/thomas/WORKBOARD.md` — remains, untouched by design).
- Janitor rescue pushes remain a hard no-op by design (Task 4's
  coordinator-review fix) — 0 real pushes made by the janitor either way,
  independent of this tap; re-enabling that is a separate, later, deliberate
  decision, not a side effect of this batch.
- Ratchet check, already true today and unaffected by this tap: both new
  gates already read as **enforcing** in `_enforcing_gates()`'s scan (via
  the `.github/workflows/gates.yml` source, verified live —
  `merge_resurrection_gate.py` and `dead_ref_gate.py` both return `True`),
  both have `RED_PATH_CASES` entries, and neither has a
  `tests/gate_selftest_baseline.json` entry (41 entries total, 0 matching
  either name) — the ratchet's `new_unwatched`/`stale`/`ghosts` checks all
  pass clean, with or without this tap.

---

STATUS: EXECUTED 2026-08-25 via owner Windows Hello (window + toggle, both re-armed immediately after). Landed as commit 28518073: pre-push dead-ref hook, leak-guard allowlist, safety-list additions incl. the registry data, merge gate wired into local commits, manifest re-signed (61 scripts, PASS), gitignore lines, changelog redaction, growth budgets 130 within the signed ceilings. Post-re-arm smokes: dead-ref refusal names its record; leak guard down to the one WORKBOARD hit; enforcement integrity PASS.
