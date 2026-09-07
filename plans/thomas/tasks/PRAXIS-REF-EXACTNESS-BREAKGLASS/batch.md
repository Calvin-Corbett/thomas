# Ref-exactness break-glass batch: the two pinned cameras stop guessing which ref they watch

STATUS: EXECUTED 2026-09-01 (owner-signed, two Windows Hello taps; commit
2c4f4808). Both diffs applied mechanically per step 3; suites revealed one
prep gap, adapted in-window and disclosed: the diff renamed
_local_branch_names to _local_branch_refs and introduced _head_ref/_ref_sha
seams the existing tests monkeypatched by old name — the three tests were
rewired to the new seams (curing two vacuous passes in the process), 12/12
green. Step-5 fixture PASS against the edited code (the dev-tag shadow is
dead in both gates). Manifest re-blessed (64, hashes only), integrity PASS,
ratchet no delta, protection re-armed immediately.

This was a **prepared** action list, not an executed one. Nothing in this
file has been run. It exists so you can review the diffs below and then
sign the whole batch with one Windows Hello tap, in the run order at the
bottom.

Source: the sibling-gates ref sweep that landed `07b088952c786cf6f5eab55263b16950bb9ea67d`
(`scripts/forge/tidy_refs.py`) and `bdc3e395f5d208957bd6faac1aba1dc04968d6f8`
(`scripts/forge/gates/release_sync_gate.py`), both mirroring the DWIM-exactness
pattern `claim_evidence.py` landed in 9ac14311/f7a523f0 (`git show-ref
--verify` on an exact, fully-qualified ref path — no DWIM fallback — sha
taken from `show-ref`'s own output, sha passed onward to `merge-base`, never
a bare name). That sweep found the identical bare-name-to-ancestry-check
shape in two more gates, `release_update_gate.py` and `worktree_branch_guard.py`
— both pinned in `agent_safety.toml`'s `[protected].enforcement_scripts`, so
neither could be edited without this ceremony. An independent adversarial
review then verified both sites are reachable by execution (a fixture
branch/tag pair, not argument) and prepared the two diffs below.

**Provenance of the diffs below**: the FIX CONTENT originates from the
adversarial review of the sibling-gates ref sweep,
`scratchpad/ref-sweep-review.md` (section C, "The pinned pair — prepared
tap-window diffs"), on this machine, 2026-08-26. That file is gitignored and
local to this machine only — this batch document is the durable, committed
record of that fix. The review's own diff TEXT, however, had a defect: both
hunk headers' declared line counts (`@@ -a,b +c,d @@`) undercounted their
own bodies — Diff 1's single hunk declared `-191,9 +191,42` but its body was
actually 11 old-side/48 new-side lines; Diff 2's three hunks declared
`17/58`, `11/12`, `18/21` but were actually `27/68`, `12/14`, `18/22`. This
made `git apply`/`patch` refuse both diffs outright ("corrupt patch" /
"malformed patch") regardless of offset drift in the target file —
confirmed against the diffs as they exist in the un-edited review file, so
the defect predates this document. The diffs embedded below are NOT that
original text. They are **mechanically regenerated** from the same,
already execution-verified end-state: the review's hunks were applied by
content (matching unchanged context, ignoring the broken declared counts)
to a scratch copy of each pristine pinned file, that scratch result was
confirmed syntactically valid and behaviorally correct (the fixture script
in step 5 below, run against it, green), and `git diff --no-index
<pristine> <that scratch result>` produced the diffs below — valid hunk
headers by construction, since `git diff` computed them itself. Round-trip
verified before this document was committed: `git apply --check` against a
fresh copy of each pinned file at HEAD succeeds for both (see the status
line below each diff), and applying them for real (`git apply`, no `--check`)
to yet another scratch copy and re-running the same fixture script is green
again. The fix content is unchanged from the review's; only the diff
TEXT's mechanics changed.

**Reachability, confirmed by execution in a fixture** (branch `dev` at
commit `c1`, tag `dev` at commit `c2` = `HEAD`, `c1` an ancestor of `c2`):
- **P1** (`worktree_branch_guard._branch_tip`): `git rev-parse --verify
  "dev^{commit}"` resolves to `c2` (the TAG — gitrevisions(7) checks
  `refs/tags/<name>` before `refs/heads/<name>`), while the real
  `refs/heads/dev` is at `c1`. `git rev-list --count HEAD..dev` then reads
  `0`: a tag literally named `dev` at HEAD silently bypasses the
  (deliberately non-suppressible) freshness/stacking check this gate exists
  to enforce.
- **P2** (`release_update_gate._merge_base_with_canonical`): `git merge-base
  HEAD dev` resolves the same way, to `c2` (the TAG), which then equals
  `_rev_parse(head)` — so the function's own "on the canonical branch
  itself, no window" guard fires and returns `None` when the real branch
  `dev` is genuinely behind and a window should be measured. (The old bare
  `"origin/dev"` candidate carries the same class one level further: it
  resolves `refs/heads/origin/dev` — a legal, creatable local branch —
  BEFORE `refs/remotes/origin/dev`, gitrevisions rule 4 before rule 5.)

---

## Diff 1 — `scripts/forge/gates/release_update_gate.py` (PINNED — do not apply outside the tap window)

**Verified**: `git apply --check` against `release_update_gate.py` at `dev`
HEAD (`bdc3e395f5d208957bd6faac1aba1dc04968d6f8`) → exit 0. Regenerated by
`git diff --no-index` from a pristine copy vs. the review's hunk applied by
content and fixture-confirmed green (see the provenance note above).

```diff
diff --git a/scripts/forge/gates/release_update_gate.py b/scripts/forge/gates/release_update_gate.py
--- a/scripts/forge/gates/release_update_gate.py
+++ b/scripts/forge/gates/release_update_gate.py
@@ -191,11 +191,48 @@ def _git_show_text(rev: str, rel_path: str) -> str | None:
     return proc.stdout
 
 
+def _ref_sha(ref: str) -> str | None:
+    """Resolve `ref` (an exact, fully-qualified path) via `git show-ref
+    --verify` -- NO DWIM fallback, so a same-named tag or nested lookalike
+    branch can never stand in for the intended ref (the landed
+    claim_evidence.py `_ref_resolves` pattern, 9ac14311/f7a523f0).
+    """
+    try:
+        proc = subprocess.run(
+            ["git", "show-ref", "--verify", ref],
+            cwd=ROOT,
+            capture_output=True,
+            text=True,
+            check=False,
+        )
+    except OSError:
+        return None
+    if proc.returncode != 0 or not (proc.stdout or "").strip():
+        return None
+    sha = (proc.stdout or "").strip().splitlines()[0].split(maxsplit=1)[0].strip()
+    return sha or None
+
+
 def _merge_base_with_canonical(head: str = "HEAD") -> str | None:
     """Merge-base with the canonical branch, or None when unresolvable."""
-    for ref in ("dev-origin/dev", "origin/dev", "dev", "origin/main", "main"):
+    # Exact, fully-qualified candidate paths -- a bare name here lets git's
+    # DWIM resolution (gitrevisions(7)) match a same-named tag before the
+    # intended branch, and a bare "origin/dev" even matches a local branch
+    # literally named origin/dev before the remote-tracking ref. `head`
+    # stays "HEAD": that is an exact $GIT_DIR/HEAD lookup (rule 1), not
+    # DWIM-reachable.
+    for ref in (
+        "refs/remotes/dev-origin/dev",
+        "refs/remotes/origin/dev",
+        "refs/heads/dev",
+        "refs/remotes/origin/main",
+        "refs/heads/main",
+    ):
+        ref_sha = _ref_sha(ref)
+        if ref_sha is None:
+            continue
         proc = subprocess.run(
-            ["git", "merge-base", head, ref],
+            ["git", "merge-base", head, ref_sha],
             cwd=ROOT,
             capture_output=True,
             text=True,
```

(The rest of the function — the `base != _rev_parse(head)` no-window guard and
both `return None` exits — is untouched; an unresolvable candidate now
`continue`s exactly where a failed merge-base used to. Hunk line numbers are
indicative — if the pinned file has drifted since this was written, re-diff
before applying; `git apply` will refuse cleanly on a genuine offset
mismatch rather than silently misapplying.)

## Diff 2 — `scripts/forge/gates/worktree_branch_guard.py` (PINNED — do not apply outside the tap window)

**Verified**: `git apply --check` against `worktree_branch_guard.py` at `dev`
HEAD (`bdc3e395f5d208957bd6faac1aba1dc04968d6f8`) → exit 0. Regenerated the
same way as Diff 1 above. Note the hunk boundaries below differ slightly
from the review's original three-hunk split (`git diff` found its own
minimal, correct hunking of the identical end state — two hunks, not three
— which is expected and immaterial; the resulting file content is byte-for-
byte the same fix).

```diff
diff --git a/scripts/forge/gates/worktree_branch_guard.py b/scripts/forge/gates/worktree_branch_guard.py
--- a/scripts/forge/gates/worktree_branch_guard.py
+++ b/scripts/forge/gates/worktree_branch_guard.py
@@ -132,30 +132,71 @@ def _topology_violations(branch: str) -> list[str]:
     return violations
 
 
-def _local_branch_names() -> list[str]:
-    """All local branch names (one per line, no leading marker)."""
+def _ref_sha(ref: str) -> str:
+    """Sha for an exact, fully-qualified ref path via `git show-ref --verify`
+    -- NO DWIM fallback, so a same-named tag can never stand in for the
+    branch this guard means to check (the landed claim_evidence.py
+    `_ref_resolves` pattern, 9ac14311/f7a523f0). Empty string when the ref
+    does not exist or cannot be read.
+    """
+    try:
+        proc = subprocess.run(
+            ["git", "show-ref", "--verify", ref],
+            cwd=ROOT,
+            capture_output=True,
+            text=True,
+            check=False,
+        )
+    except OSError:
+        return ""
+    if proc.returncode != 0 or not (proc.stdout or "").strip():
+        return ""
+    return (proc.stdout or "").strip().splitlines()[0].split(maxsplit=1)[0].strip()
+
+
+def _head_ref() -> str:
+    """Full refname HEAD points at (e.g. refs/heads/dev); '' when detached.
+    `symbolic-ref` reads .git/HEAD directly -- no DWIM resolution."""
     proc = subprocess.run(
-        ["git", "for-each-ref", "--format=%(refname:short)", "refs/heads/"],
+        ["git", "symbolic-ref", "--quiet", "HEAD"],
         cwd=ROOT,
         capture_output=True,
         text=True,
     )
-    if proc.returncode != 0:
-        return []
-    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]
+    return proc.stdout.strip() if proc.returncode == 0 else ""
 
 
-def _branch_tip(name: str) -> str:
-    """Commit hash at the tip of `name`. Empty string if the branch is unknown."""
+def _local_branch_refs() -> list[tuple[str, str]]:
+    """(bare_name, full_refname) for every local branch. The bare name is
+    cut from for-each-ref's own %(refname) -- never from %(refname:short),
+    whose disambiguation lengthens under a same-named tag (e.g. to
+    heads/topic) and would then denote a different ref."""
     proc = subprocess.run(
-        ["git", "rev-parse", "--verify", f"{name}^{{commit}}"],
+        ["git", "for-each-ref", "--format=%(refname)", "refs/heads/"],
         cwd=ROOT,
         capture_output=True,
         text=True,
     )
     if proc.returncode != 0:
-        return ""
-    return proc.stdout.strip()
+        return []
+    out: list[tuple[str, str]] = []
+    for line in proc.stdout.splitlines():
+        full = line.strip()
+        if full.startswith("refs/heads/"):
+            out.append((full[len("refs/heads/") :], full))
+    return out
+
+
+def _branch_tip(name: str) -> str:
+    """Commit hash at the tip of BRANCH `name`. Empty string if unknown.
+    Resolved as the exact path refs/heads/<name> (or as given when already
+    fully qualified) -- the old bare-name `rev-parse --verify
+    {name}^{{commit}}` let a same-named tag shadow the branch
+    (gitrevisions(7) tries refs/tags/ before refs/heads/), so a stray tag
+    `dev` at HEAD silently bypassed the freshness check.
+    """
+    ref = name if name.startswith("refs/") else f"refs/heads/{name}"
+    return _ref_sha(ref)
 
 
 def _is_ancestor(commit: str, ref: str) -> bool:
@@ -201,8 +242,10 @@ def _commits_behind(base: str) -> int | None:
     tip = _branch_tip(base)
     if not tip:
         return None
+    # `tip` is a sha -- passing the bare `base` name here would re-run the
+    # DWIM resolution _branch_tip just avoided.
     proc = subprocess.run(
-        ["git", "rev-list", "--count", f"HEAD..{base}"],
+        ["git", "rev-list", "--count", f"HEAD..{tip}"],
         cwd=ROOT,
         capture_output=True,
         text=True,
@@ -360,15 +403,19 @@ def run(_argv: Sequence[str] | None = None) -> int:
     # Topic branches must start directly from canonical base branches
     # (master, main, release/oss-launch, publish-clean).
     if _is_topic_branch(branch):
-        current_tip = _branch_tip(branch)
+        # The current branch's tip comes from HEAD's own full refname --
+        # `branch` (from --abbrev-ref) can be a lengthened short form under
+        # a same-named tag, which refs/heads/-qualifying would then miss.
+        head_ref = _head_ref()
+        current_tip = _ref_sha(head_ref) if head_ref else ""
         if current_tip:
             base_tips = {name: _branch_tip(name) for name in CANONICAL_BASE_BRANCHES}
-            local_branches = _local_branch_names()
+            local_branches = _local_branch_refs()
             unmerged_ancestors: list[str] = []
-            for other in local_branches:
-                if other == branch or not _is_topic_branch(other):
+            for other, other_full in local_branches:
+                if other_full == head_ref or not _is_topic_branch(other):
                     continue
-                other_tip = _branch_tip(other)
+                other_tip = _ref_sha(other_full)
                 if not other_tip or not _is_ancestor(other_tip, current_tip):
                     continue
                 already_merged = any(base_tip and _is_ancestor(other_tip, base_tip) for base_tip in base_tips.values())
```

(`_is_ancestor` needs no edit — after these changes every argument it receives
is already a sha. `_branch_name()` is deliberately untouched: its output feeds
display and `expected_by_branch` config keys, and changing detached-HEAD
behavior is out of this sweep's scope. Hunk line numbers are indicative — if
the pinned file has drifted since this was written, re-diff before applying;
`git apply` will refuse cleanly on a genuine offset mismatch rather than
silently misapplying.)

---

## Why a separate tap, not a growth of tap #3

Tap #3 (`plans/thomas/tasks/PRAXIS-PHASE14-BREAKGLASS/batch.md`) is already
prepared and independently verified as a batch covering five unrelated
changes (evidence-gate promotion, problem-closure-gate promotion, an
`accepted_risks.json` protection, a graveyard append, a `.gitignore`/CSS
landing). Folding these two diffs into it would re-open verification of
everything already in it and couple this pair's rollback to five unrelated
changes, while a small, homogeneous "DWIM-exactness, pinned pair" tap is
verifiable in minutes and revertable in one step. The ceremony cost of a
second Windows Hello tap is smaller than the re-verification cost of a
mutated batch — this was the reviewing session's explicit routing call, not
a default.

## Run order

Everything below is one pass you sign with a single tap. Nothing executes
until you run step 1. Two separate break-glass mechanisms are involved, the
same two prior taps used and re-armed afterward: the **window**
(human-presence tap, gates a protected-file edit) and the **toggle**
(disables `runtime_protection_disabled`-aware gates outright while it's
off). Both must be re-armed at the end regardless of how the tap goes.
Editing the CONTENT of two `enforcement_scripts` entries changes their hash,
so the integrity manifest must be regenerated too — same manifest-last rule
tap #3 already follows, for the same reason: regenerating any earlier
freezes a hash the next edit invalidates.

1. `python scripts/breakglass_window.py on` — opens the time-boxed
   human-presence window `protected_files_gate.py`'s breakglass/approval-
   trailer path checks.
2. `python scripts/runtime_protection_toggle.py off` — disables the
   `runtime_protection_disabled`-aware gates for the duration of this edit.
   Requires its own Windows credential prompt.
3. Apply both diffs mechanically — save each fenced block above to a file
   (or pipe it directly) and run:
   ```
   git apply diff1-release-update-gate.patch
   git apply diff2-worktree-branch-guard.patch
   ```
   Both were `git apply --check`-verified against `dev` HEAD before this
   document was committed (see the status line above each diff). If either
   apply fails, the pinned file has drifted since this was written — do not
   force it; re-diff by hand against the current file and treat the diffs
   above as reference, not gospel.
4. Run each gate's existing suite:
   ```
   .venv/Scripts/python.exe -m pytest tests/test_check_release_update_gate_script.py tests/test_check_worktree_branch_guard.py -q
   ```
5. Run the two shadow-attack fixtures below (the review's `replay.py` is
   gitignored and local to the reviewing session only — this inline script
   is the durable copy of what it needs to prove; it builds ONE fixture repo
   and exercises both fixed functions against it, confirming the same
   post-fix behavior the review confirmed by execution in section A):
   ```
   python - <<'PY'
   import subprocess, sys, tempfile
   from pathlib import Path

   d = Path(tempfile.mkdtemp())

   def g(*args):
       subprocess.run(["git", *args], cwd=d, check=True, capture_output=True, text=True)

   g("init", "-b", "dev")
   g("config", "user.name", "t")
   g("config", "user.email", "t@t.com")
   g("config", "tag.gpgsign", "false")  # this machine's global tag.gpgsign=true would else demand a signing key
   (d / "a.txt").write_text("a")
   g("add", "a.txt")
   g("commit", "-m", "c1 (real dev branch tip)")
   c1 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=d, capture_output=True, text=True).stdout.strip()
   g("checkout", "-b", "work")
   (d / "b.txt").write_text("b")
   g("add", "b.txt")
   g("commit", "-m", "c2 (HEAD, descendant of c1)")
   c2 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=d, capture_output=True, text=True).stdout.strip()
   g("tag", "dev")  # a tag literally named "dev", at HEAD -- shadows the real refs/heads/dev at c1

   import scripts.forge.gates.release_update_gate as rug
   import scripts.forge.gates.worktree_branch_guard as wbg
   rug.ROOT = d
   wbg.ROOT = d

   base = rug._merge_base_with_canonical()
   print(f"P2 release_update_gate._merge_base_with_canonical() -> {base}")
   assert base == c1, f"expected the real branch tip {c1}, got {base} (the tag if this fails)"

   tip = wbg._branch_tip("dev")
   print(f"P1 worktree_branch_guard._branch_tip('dev') -> {tip}")
   assert tip == c1, f"expected the real branch tip {c1}, got {tip} (the tag if this fails)"

   print("PASS: both gates resolve the real branch, not the same-named tag shadowing it.")
   PY
   ```
   Both assertions must hold (script exits 0 and prints `PASS`) before
   proceeding — this is the red/green proof for the window, run against the
   code you just edited in step 3, not a claim carried over from the review.
   (`_commits_behind` is deliberately not asserted here: in this fixture's
   topology — the real `dev` branch is an ANCESTOR of `HEAD` — its correct
   value is `0` both before and after the fix, since `HEAD` genuinely has
   every commit `dev` has; the P1 bug this fixture proves is in
   `_branch_tip`'s resolved SHA, which `_commits_behind` also consumes, not
   in this particular fixture's numeric output. The review's own execution
   run (section A, T1/T2 in the janitor and the P1/P2 fixture here) already
   covers the ancestry-resolution defect end to end.)
6. Run `python scripts/forge/gates/enforcement_integrity.py
   --generate-manifest` — re-blesses `scripts/forge/gates/enforcement_manifest.json`'s
   hashes for `release_update_gate.py` and `worktree_branch_guard.py`
   against their new content (the `enforcement_scripts` list itself is
   unchanged — no entry added or removed, so the entry COUNT stays whatever
   it is today — only these two entries' hashes change).
7. Review the diff on every touched file: `scripts/forge/gates/release_update_gate.py`,
   `scripts/forge/gates/worktree_branch_guard.py`, and
   `scripts/forge/gates/enforcement_manifest.json`.
8. Commit the three files in one commit via the sanctioned wrapper:
   ```
   .venv/Scripts/python.exe scripts/crew/brief/commit.py --agent <your-agent-id> \
     --include scripts/forge/gates/release_update_gate.py \
     --include scripts/forge/gates/worktree_branch_guard.py \
     --include scripts/forge/gates/enforcement_manifest.json \
     --allow-scope-fallback \
     --fallback-reason "PRAXIS-REF-EXACTNESS-BREAKGLASS tap: applying the reviewer-prepared, execution-verified DWIM-exactness diffs to the two pinned ancestry-check gates" \
     --message "fix(gates): the last two pinned cameras stop guessing which ref they watch"
   ```
   The protected-files gate's breakglass/approval-trailer path (open since
   step 1) covers this commit.
9. `python scripts/runtime_protection_toggle.py on` — re-arms runtime
   protection.
10. `python scripts/breakglass_window.py off` — closes the human-presence
    window.

**Smoke tests — run AFTER step 10, outside the protection-off window**
(same pattern tap #3 uses: verify after landing, not while the window is
open):

```
python scripts/forge/gates/enforcement_integrity.py                                 # integrity check passes against the freshly-generated manifest
.venv/Scripts/python.exe -m pytest tests/test_check_release_update_gate_script.py tests/test_check_worktree_branch_guard.py -q   # both gates' existing suites, unchanged, still green
.venv/Scripts/python.exe -m pytest tests/test_no_gate_enforces_unwatched.py -q       # ratchet: no delta, these two gates were already covered
```

---

## Cross-references

- **Tap #3** (`plans/thomas/tasks/PRAXIS-PHASE14-BREAKGLASS/batch.md`) is
  untouched and unblocked by this document — it is a separate, independently
  signable ceremony (see the rationale above); nothing in it depends on this
  tap landing first or vice versa.
- **`tidy_refs.py`'s Minor residual** (short-name bookkeeping desync under a
  tag shadow: `classify_branches`'s display/bucket-key path, the
  `{base, current}` exclusion, `_branch_checked_out`, the upstream
  `rev-list --count` probe, and the `git branch -d/-D` apply path still key
  off `%(refname:short)`, which lengthens to e.g. `heads/dev` under a tag
  shadow — reproduced by the review: dry-run mislabels the base branch
  itself as `would delete: heads/dev (merged into dev)`, and `git branch -d
  heads/dev` then fails noisily, `rc=1`, `refs/heads/dev` survives) is
  explicitly **not** part of this tap. It is cosmetic-to-noisy only — never
  silent loss of unmerged work, since `-d` refuses anything unmerged — and
  is tracked as a plain follow-up against `scripts/forge/tidy_refs.py`
  (not pinned, no ceremony needed), not queued here.

---

STATUS: PREPARED
