# Phase 0 Remainder + Watcher-of-the-Watchers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish spec phase 0 (worktree consolidation tooling + break-glass batch prep) and build phase 1.1: a selftest harness proving every enforcing gate can actually fail.

**Architecture:** A report-only worktree triage tool feeds an owner-checkpointed consolidation pass. The gate selftest harness runs gates as subprocesses through the real `scripts/_gate_python.py` shim (so the shim's exit-code behavior is under test too — the July failure was the shim swallowing exit codes), asserting each gate exits non-zero on a violating fixture. A shrink-only baseline ratchet forces every enforcing gate toward coverage without demanding all 58 at once.

**Tech Stack:** Python 3.12, pytest, git CLI via subprocess. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-24-praxis-first-design.md` (phases 0.3, 0.4, 1.1)

## Global Constraints

- **Commits go through the wrapper, never raw git commit:** `.venv/Scripts/python.exe scripts/crew/brief/commit.py --agent claude --include <paths> --allow-scope-fallback --fallback-reason "owner-authorized praxis-first plan execution" --message $'<subject>\n\n<body>\n\nThomas-Agent: claude\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>'` (Bash tool, ANSI-C quoting).
- **NO double-quote characters anywhere inside the commit message** — commit.py silently fails on them. Verify landing with `git status --porcelain -- <paths>` (empty = landed), never by grepping output.
- **If `CHANGELOG.md` is dirty before committing:** `git stash push -m park -- CHANGELOG.md` → commit → `git stash pop` (three separate tool calls, never one compound command).
- **Keep each commit under 3 code files** so the changelog gate does not fire (module + test = 2).
- **Run `ruff check <file>` and `ruff format <file>` on every Python file you touch before committing** — commit.py does not run ruff for you.
- **Never create files matching `*_part*.py`.** Never use `exec()` to load code.
- **Do not modify files listed in `agent_safety.toml` [protected_files]** — Task 5 prepares (but does not execute) the owner-signed batch for those.
- **New files under 800 lines** (monolith soft cap; hard cap 1200).
- **Test files are named as sentences** per repo convention, e.g. `tests/test_a_finished_build_is_not_a_crash.py`.
- **Before `git worktree remove --force`, ALWAYS check for a `.venv` junction inside the worktree** (`Get-Item <wt>\.venv | Select-Object LinkType` or `ls -la`); removing through a junction destroys the main venv. This is a hard rule from a real incident.
- **Related untracked work in the tree:** `tests/test_a_gate_must_scan_the_repository_it_guards.py` (red-path test for monolith_guard's repo-root bug) already exists untracked. Task 3 coordinates with it; do not delete or rewrite it.

---

### Task 1: Worktree triage report tool

**Files:**
- Create: `scripts/forge/worktree_triage.py`
- Test: `tests/test_a_worktree_report_counts_what_it_would_lose.py`

**Interfaces:**
- Produces: `triage(repo_root: Path) -> list[dict]` where each dict has keys `path` (str), `branch` (str or ""), `dirty_files` (int), `unique_commits` (int, commits unreachable from `dev`), `last_commit_date` (str ISO date or ""), `has_venv_junction` (bool), `disposition` (str: `"removable"` when dirty_files==0 and unique_commits==0, else `"needs-review"`). CLI: `python scripts/forge/worktree_triage.py [--repo-root PATH] [--json]` prints a markdown table (or JSON), always exits 0 (report-only, like `scripts/failure_string_reachability_report.py`).
- Consumes: nothing from other tasks.

- [ ] **Step 1: Write the failing test**

```python
"""A worktree report must count dirty files and unique commits before anyone
deletes anything -- 'removable' may only mean: nothing would be lost."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL = REPO_ROOT / "scripts" / "forge" / "worktree_triage.py"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def _make_repo_with_worktrees(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(tmp_path, "init", "-b", "dev", "repo")
    (repo / "a.txt").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "base")
    # clean worktree, no unique commits -> removable
    _git(repo, "worktree", "add", str(tmp_path / "wt_clean"), "-b", "wt-clean")
    # dirty worktree with a unique commit -> needs-review
    _git(repo, "worktree", "add", str(tmp_path / "wt_dirty"), "-b", "wt-dirty")
    wt_dirty = tmp_path / "wt_dirty"
    (wt_dirty / "b.txt").write_text("unique\n", encoding="utf-8")
    _git(wt_dirty, "add", "b.txt")
    _git(wt_dirty, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "unique")
    (wt_dirty / "c.txt").write_text("uncommitted\n", encoding="utf-8")
    return repo


def test_clean_merged_worktree_is_removable_and_dirty_one_is_not(tmp_path):
    repo = _make_repo_with_worktrees(tmp_path)
    sys.path.insert(0, str(REPO_ROOT))
    from scripts.forge.worktree_triage import triage

    rows = {Path(r["path"]).name: r for r in triage(repo)}
    assert rows["wt_clean"]["dirty_files"] == 0
    assert rows["wt_clean"]["unique_commits"] == 0
    assert rows["wt_clean"]["disposition"] == "removable"
    assert rows["wt_dirty"]["dirty_files"] == 1
    assert rows["wt_dirty"]["unique_commits"] == 1
    assert rows["wt_dirty"]["disposition"] == "needs-review"


def test_cli_always_exits_zero_and_prints_every_worktree(tmp_path):
    repo = _make_repo_with_worktrees(tmp_path)
    proc = subprocess.run(
        [sys.executable, str(TOOL), "--repo-root", str(repo)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0
    assert "wt_clean" in proc.stdout and "wt_dirty" in proc.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_a_worktree_report_counts_what_it_would_lose.py -v`
Expected: FAIL with `ModuleNotFoundError` / `No module named 'scripts.forge.worktree_triage'`

- [ ] **Step 3: Write the implementation**

```python
"""Report-only worktree triage: what exists, what is dirty, what would be lost.

Never deletes anything. Always exits 0 (a report that can block is a gate;
this is an instrument). Disposition 'removable' means provably nothing lost:
zero dirty files AND zero commits unreachable from dev.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_REPORT_ERRORS = (OSError, subprocess.SubprocessError, ValueError)


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True
    )
    return proc.stdout if proc.returncode == 0 else ""


def _worktree_paths(repo_root: Path) -> list[tuple[Path, str]]:
    out = _git(repo_root, "worktree", "list", "--porcelain")
    pairs: list[tuple[Path, str]] = []
    path, branch = None, ""
    for line in out.splitlines() + [""]:
        if line.startswith("worktree "):
            path = Path(line[len("worktree "):])
        elif line.startswith("branch "):
            branch = line[len("branch "):].removeprefix("refs/heads/")
        elif not line:
            if path is not None:
                pairs.append((path, branch))
            path, branch = None, ""
    return pairs


def triage(repo_root: Path) -> list[dict]:
    rows: list[dict] = []
    for path, branch in _worktree_paths(repo_root):
        if path.resolve() == repo_root.resolve():
            continue  # the main checkout is not a triage candidate
        dirty = len(_git(path, "status", "--porcelain").splitlines())
        head = _git(path, "rev-parse", "HEAD").strip()
        unique = len(
            _git(repo_root, "rev-list", f"dev..{head}").splitlines()
        ) if head else 0
        last = _git(path, "log", "-1", "--format=%cs").strip()
        venv = path / ".venv"
        has_junction = venv.is_symlink() if venv.exists() else False
        rows.append({
            "path": str(path),
            "branch": branch,
            "dirty_files": dirty,
            "unique_commits": unique,
            "last_commit_date": last,
            "has_venv_junction": bool(has_junction),
            "disposition": "removable" if dirty == 0 and unique == 0 else "needs-review",
        })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[3])
    ap.add_argument("--json", action="store_true")
    ns = ap.parse_args()
    try:
        rows = triage(ns.repo_root)
    except _REPORT_ERRORS as exc:
        print(f"triage report incomplete: {exc}")
        return 0
    if ns.json:
        print(json.dumps(rows, indent=1))
        return 0
    print("| worktree | branch | dirty | unique commits | last commit | venv-junction | disposition |")
    print("|---|---|---|---|---|---|---|")
    for r in rows:
        print(
            f"| {Path(r['path']).name} | {r['branch']} | {r['dirty_files']} "
            f"| {r['unique_commits']} | {r['last_commit_date']} "
            f"| {'YES' if r['has_venv_junction'] else 'no'} | {r['disposition']} |"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Note on junction detection: `Path.is_symlink()` returns True for Windows junctions on Python 3.12 (junctions are reparse points; `os.path.islink` covers them since 3.8+ behavior changes — verify on this machine with a quick check against a known junction if any `needs-review` worktree shows one; the tests do not depend on it).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_a_worktree_report_counts_what_it_would_lose.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Lint and commit**

Run: `ruff check scripts/forge/worktree_triage.py tests/test_a_worktree_report_counts_what_it_would_lose.py` then `ruff format` on the same paths.
Commit per Global Constraints, subject: `feat(forge): worktree triage report - what exists, what would be lost`

### Task 2: Consolidation pass (operational, owner-checkpointed)

**Files:**
- Create: `plans/thomas/tasks/PRAXIS-PHASE0-WORKTREES/salvage_report.md` (generated)
- Modify: none (removals are git operations, not file edits)

**Interfaces:**
- Consumes: `worktree_triage.py` CLI from Task 1.
- Produces: a shrinking worktree list; the salvage report for the owner.

- [ ] **Step 1: Generate the report**

Create the directory, then run: `.venv/Scripts/python.exe scripts/forge/worktree_triage.py > plans/thomas/tasks/PRAXIS-PHASE0-WORKTREES/salvage_report.md` and again with `--json > .../salvage_report.json` (keep both; the JSON is the machine copy).

- [ ] **Step 2: Remove ONLY `removable` worktrees**

For each row with disposition `removable` AND `has_venv_junction` false: re-verify by hand (`git -C <wt> status --porcelain` prints nothing AND `git rev-list dev..<wt-head>` prints nothing), then `git worktree remove <path>` (clean trees need no `--force`). If `has_venv_junction` is YES, skip it and flag it in the report — owner decides.

- [ ] **Step 3: STOP — owner checkpoint**

Every `needs-review` worktree stays untouched and listed with its dirty count and unique commits. Do NOT remove any of them. The `%TEMP%` worktrees with 10,000+ uncommitted files (base/fin2/fin3/fin4/final/full) are in this group. Present the report; wait for per-worktree or per-group direction.

- [ ] **Step 4: Commit the report**

Commit `plans/thomas/tasks/PRAXIS-PHASE0-WORKTREES/salvage_report.md` per Global Constraints, subject: `chore(worktrees): triage report - removable removed, the rest awaits your call`

### Task 3: Gate selftest harness with the first red-path proof

**Files:**
- Create: `tests/test_every_enforcing_gate_can_fail.py`
- Test: (self — this file IS the test)

**Interfaces:**
- Produces: `RED_PATH_CASES: dict[str, callable]` mapping gate filename (e.g. `"monolith_guard.py"`) to a fixture-builder `(tmp_path: Path) -> tuple[list[str], Path]` returning (CLI args, cwd). Task 4's ratchet imports this dict. Also `run_gate_through_shim(gate: str, args: list[str], cwd: Path) -> subprocess.CompletedProcess`.
- Consumes: `scripts/_gate_python.py` (the real shim — invoking it IS the point).

- [ ] **Step 1: Read the target gate's real interface**

Run: `.venv/Scripts/python.exe scripts/forge/gates/monolith_guard.py --help`
Record the exact flag names for repo root and staged-only mode in the test docstring. (Known from the sibling test `tests/test_a_gate_must_scan_the_repository_it_guards.py`: `--staged-only` and `--repo-root` exist; the hard limit is 1200 lines.)

- [ ] **Step 2: Write the failing test**

```python
"""Every enforcing gate must be able to fail -- and prove it through the shim.

The July failure was not a broken gate: 28 gates ran through
scripts/_gate_python.py, which swallowed exit codes on Windows, so every
violation printed advice and exited 0. A gate red-path test that bypasses the
shim would re-create that blind spot. So: violating fixture -> run through the
REAL shim -> assert non-zero exit AND the violation named in output.

RED_PATH_CASES is the coverage registry; the ratchet test
(test_no_gate_enforces_unwatched.py) forces it to grow until every enforcing
gate has an entry.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SHIM = REPO_ROOT / "scripts" / "_gate_python.py"
GATES = REPO_ROOT / "scripts" / "forge" / "gates"


def run_gate_through_shim(gate: str, args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SHIM), str(GATES / gate), *args],
        capture_output=True, text=True, cwd=str(cwd),
    )


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def _monolith_violation(tmp_path: Path) -> tuple[list[str], Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(tmp_path, "init", "-b", "dev", "repo")
    big = repo / "huge_module.py"
    big.write_text("\n".join(f"x{i} = {i}" for i in range(1301)) + "\n", encoding="utf-8")
    _git(repo, "add", "huge_module.py")
    return (["--staged-only", "--repo-root", str(repo)], repo)


RED_PATH_CASES = {
    "monolith_guard.py": _monolith_violation,
}


def test_monolith_guard_fails_loudly_on_a_1301_line_staged_file(tmp_path):
    args, cwd = RED_PATH_CASES["monolith_guard.py"](tmp_path)
    proc = run_gate_through_shim("monolith_guard.py", args, cwd)
    combined = proc.stdout + proc.stderr
    assert proc.returncode != 0, (
        "gate exited 0 on a hard-limit violation -- the July disease:\n" + combined
    )
    assert "huge_module.py" in combined, (
        "gate failed but did not name the violating file:\n" + combined
    )
```

- [ ] **Step 3: Run the gate manually against the fixture to see its true red output**

Build the fixture by hand in a temp dir (same commands as `_monolith_violation`), then:
`.venv/Scripts/python.exe scripts/_gate_python.py scripts/forge/gates/monolith_guard.py --staged-only --repo-root <tmpdir>/repo`
Expected: non-zero exit, output naming `huge_module.py`. If the flag spelling differs from Step 1's `--help` output, fix the fixture args — not the assertion.

- [ ] **Step 4: Run the test**

Run: `.venv/Scripts/python.exe -m pytest tests/test_every_enforcing_gate_can_fail.py -v`
Expected: PASS. If it FAILS with exit 0 from the shim, you have re-found the July disease live — stop and report before anything else; that is a phase-1.1 emergency finding, not a test bug.

- [ ] **Step 5: Lint and commit**

`ruff check` + `ruff format` the test file. Commit per Global Constraints, subject: `test(gates): a gate that cannot fail is not a gate - red-path harness, first proof`

### Task 4: The coverage ratchet

**Files:**
- Create: `tests/test_no_gate_enforces_unwatched.py`
- Create: `tests/gate_selftest_baseline.json`

**Interfaces:**
- Consumes: `RED_PATH_CASES` from `tests/test_every_enforcing_gate_can_fail.py`; `.pre-commit-config.yaml`; `LOCAL_GATE_COMMANDS` in `scripts/crew/brief/commit.py`.
- Produces: `tests/gate_selftest_baseline.json` — a JSON array of gate filenames not yet covered. It may only shrink.

- [ ] **Step 1: Write the failing test**

```python
"""No gate may join the enforcing set without a red-path selftest.

The enforcing set = every gates/*.py named in .pre-commit-config.yaml plus
commit.py's LOCAL_GATE_COMMANDS. Gates without a RED_PATH_CASES entry must be
listed in gate_selftest_baseline.json (the debt list). The baseline may only
shrink: an entry that gains coverage must be deleted, and a NEW enforcing gate
may never be added to it. That is the ratchet."""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE = Path(__file__).with_name("gate_selftest_baseline.json")


def _enforcing_gates() -> set[str]:
    names: set[str] = set()
    pat = re.compile(r"scripts[/\\]forge[/\\]gates[/\\]([A-Za-z0-9_]+\.py)")
    for source in (
        REPO_ROOT / ".pre-commit-config.yaml",
        REPO_ROOT / "scripts" / "crew" / "brief" / "commit.py",
    ):
        names.update(pat.findall(source.read_text(encoding="utf-8")))
    return names


def test_every_enforcing_gate_is_covered_or_explicitly_in_debt():
    from tests.test_every_enforcing_gate_can_fail import RED_PATH_CASES

    enforcing = _enforcing_gates()
    covered = set(RED_PATH_CASES)
    baseline = set(json.loads(BASELINE.read_text(encoding="utf-8")))
    uncovered = enforcing - covered
    new_unwatched = uncovered - baseline
    assert not new_unwatched, (
        f"enforcing gates with no red-path selftest and no baseline entry: "
        f"{sorted(new_unwatched)} -- write the selftest or it does not enforce"
    )
    stale = baseline & covered
    assert not stale, (
        f"baseline entries that now have coverage -- delete them (the ratchet "
        f"only turns one way): {sorted(stale)}"
    )
    ghosts = baseline - enforcing
    assert not ghosts, f"baseline lists gates that no longer enforce: {sorted(ghosts)}"
```

- [ ] **Step 2: Run to see the true uncovered list**

Run: `.venv/Scripts/python.exe -m pytest tests/test_no_gate_enforces_unwatched.py -v`
Expected: FAIL (baseline file missing). The assertion trace lists every currently-uncovered enforcing gate.

- [ ] **Step 3: Seed the baseline with exactly that list**

Write `tests/gate_selftest_baseline.json` as a sorted JSON array of the gate filenames from the failure output (everything except `monolith_guard.py`). No other content, no comments (JSON).

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_no_gate_enforces_unwatched.py tests/test_every_enforcing_gate_can_fail.py -v`
Expected: all PASS.

- [ ] **Step 5: Lint and commit**

`ruff check` + `ruff format` the test. Commit both files per Global Constraints (2 files), subject: `test(gates): the ratchet - no new gate enforces unwatched, the debt list only shrinks`

### Task 5: Break-glass batch prep (prepare, never execute)

**Files:**
- Create: `plans/thomas/tasks/PRAXIS-PHASE0-BREAKGLASS/batch.md`

**Interfaces:**
- Consumes: `scripts/forge/gates/monolith_guard.py --help` (baseline flag names); `scripts/forge/gates/enforcement_manifest.json` (flat `{path: sha256}` dict); the standing break-glass flow (`scripts/breakglass_auth.py` window on → action → off).
- Produces: a ready-to-sign action list the owner executes as one Windows Hello tap.

- [ ] **Step 1: Measure the four files against the cap**

Run: `wc -l thomas/agent/loop_execution.py thomas/core/llm_client.py thomas/core/run_store.py scripts/crew/brief/commit.py` — record exact counts (spec cites 982/833/929/846; re-measure, the tree moves).

- [ ] **Step 2: Write the batch document**

`batch.md` must contain, concretely: (a) the four files with measured line counts and the per-file choice — baseline entry (with expiry date, owner, and max_growth in the exact field shape used by `docs/ops/monolith_baseline_approvals` — read one existing entry there and copy its shape) or pre-split (name the proposed module boundaries, one line each); (b) the exact `enforcement_manifest.json` regeneration command — find its entry point with `grep -rn "manifest" scripts/forge/gates/enforcement_integrity.py | head` — plus the list of gate/crew files whose hashes phase 1 will change; (c) the run order: breakglass window ON → baseline/approvals edits → manifest regen → window OFF; (d) a final line: `STATUS: PREPARED - awaiting owner tap. Nothing in this file has been executed.`

- [ ] **Step 3: Verify nothing was executed**

Run: `git status --porcelain -- agent_safety.toml scripts/forge/gates/enforcement_manifest.json docs/ops/` — must show no NEW modifications from this task (the pre-existing dirty state of `enforcement_manifest.json` noted at session start is not yours; do not touch it).

- [ ] **Step 4: Commit the batch doc**

Commit per Global Constraints, subject: `docs(phase0): break-glass batch prepared - one tap, nothing executed`

---

## Self-review notes

- Spec coverage: phase 0.3 → Tasks 1–2; phase 0.4 → Task 5; phase 1.1 → Tasks 3–4. Phase 0.1/0.2 were already executed 2026-08-24 (`defuse_phase0.py --apply`: branches deleted and verified, janitor startup VBS caged). Phases 1.2–1.5, 2, and 3 get their own plans per the spec's ordering.
- The untracked `tests/test_a_gate_must_scan_the_repository_it_guards.py` overlaps Task 3 in spirit, not in content (it pins the repo-root bug; Task 3 pins the red path through the shim). Both should exist.
- Type consistency: `RED_PATH_CASES` name and fixture-builder signature match between Tasks 3 and 4; `triage()` row keys match between Task 1's test and implementation.
