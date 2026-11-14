"""Every enforcing gate must be able to fail -- and prove it through the shim.

The July failure was not a broken gate: 28 gates ran through
scripts/_gate_python.py, which swallowed exit codes on Windows, so every
violation printed advice and exited 0. A gate red-path test that bypasses the
shim would re-create that blind spot. So: violating fixture -> run through the
REAL shim -> assert non-zero exit AND the violation named in output.

RED_PATH_CASES is the coverage registry; the ratchet test
(test_no_gate_enforces_unwatched.py) forces it to grow until every enforcing
gate has an entry.

Step 1 record (monolith_guard.py --help, run under .venv/Scripts/python.exe):
    --repo-root REPO_ROOT   Repository root (default: inferred from script location).
    --baseline BASELINE     Baseline JSON path (default: docs/monolith_guard_baseline.json).
    --base BASE              Optional git base ref for growth checks.
    --head HEAD              Optional git head ref for growth checks (default: HEAD).
    --staged-only            Scan only files currently staged in git index.
    --json                   Print JSON output.
Hard limit for .py files is 1200 lines (DEFAULT_HARD_LIMITS in monolith_guard.py).
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SHIM = REPO_ROOT / "scripts" / "_gate_python.py"
GATES = REPO_ROOT / "scripts" / "forge" / "gates"


def run_gate_through_shim(gate: str, args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SHIM), str(GATES / gate), *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
    )


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def _monolith_violation(tmp_path: Path) -> tuple[list[str], Path]:
    """The explicit --repo-root form: honest and reliable against a tmp
    fixture, but NOT the invocation form pre-commit actually uses (see
    test_monolith_guard_pre_commit_form_catches_the_fixture_violation below
    for what that form does and does not cover)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(tmp_path, "init", "-b", "dev", "repo")
    big = repo / "huge_module.py"
    big.write_text("\n".join(f"x{i} = {i}" for i in range(1301)) + "\n", encoding="utf-8")
    _git(repo, "add", "huge_module.py")
    return (["--staged-only", "--repo-root", str(repo)], repo)


def _merge_resurrection_violation(tmp_path: Path) -> tuple[list[str], Path]:
    """A dead file path re-staged as an ADD with no resurrection approval.
    Uses the real graveyard.py API to write the fixture's death record --
    never hand-written JSON -- so this breaks the same way production would
    if the record shape ever changed."""
    from scripts.forge import graveyard

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(tmp_path, "init", "-b", "dev", "repo")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    graveyard.record_death(
        repo, "file", "old/retired_module.py", "deadbeef", reason="replaced by new/module.py", by="test-suite"
    )
    retired = repo / "old" / "retired_module.py"
    retired.parent.mkdir(parents=True, exist_ok=True)
    retired.write_text("content\n", encoding="utf-8")
    _git(repo, "add", "old/retired_module.py")
    return (["--repo-root", str(repo)], repo)


def _workboard_evidence_violation(tmp_path: Path) -> tuple[list[str], Path]:
    """A task's Active Task line flips to `status=done` with no `evidence=`
    field, staged with no commit -- the same shape any writer (today's
    reactivate.py, or a future writer routed through issue.py's pinned,
    evidence-blind `_set_task_status`) would produce if it skipped the
    evidence requirement. The board content is hand-written directly, never
    built through claim_evidence.py or reactivate.py: this fixture proves
    the gate reads the board DIFF itself, not any particular writer's call
    path (see workboard_evidence_gate.py's module docstring, "WHY THIS GATE
    EXISTS AS THE NET")."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(tmp_path, "init", "-b", "dev", "repo")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    board = repo / "plans" / "thomas" / "WORKBOARD.md"
    board.parent.mkdir(parents=True, exist_ok=True)
    board.write_text(
        "# Test Workboard\n\n## Active Tasks\n\n"
        "- task_id=evidence-red-path; agent=agent1; scope=foo; summary=do the thing; status=in_progress\n"
        "## Up For Grabs\n\n- none\n",
        encoding="utf-8",
        newline="\n",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial board")
    board.write_text(
        "# Test Workboard\n\n## Active Tasks\n\n"
        "- task_id=evidence-red-path; agent=agent1; scope=foo; summary=do the thing; status=done\n"
        "## Up For Grabs\n\n- none\n",
        encoding="utf-8",
        newline="\n",
    )
    _git(repo, "add", "plans/thomas/WORKBOARD.md")
    return (["--repo-root", str(repo)], repo)


def _problem_closure_violation(tmp_path: Path) -> tuple[list[str], Path]:
    """An incident (Task Problems entry + its PROBLEM.md) resolving with NO
    `closure:` line at all -- the shape this gate exists to catch: closure is
    the gate's whole point, so a missing closure line on a resolving
    incident is always a FAIL, never an unreadable-registry pass. The board
    and PROBLEM.md content are hand-written directly, the same shape any
    writer (a hand-edit, or a future automated resolver) would produce if it
    skipped the closure requirement."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(tmp_path, "init", "-b", "dev", "repo")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    board = repo / "plans" / "thomas" / "WORKBOARD.md"
    board.parent.mkdir(parents=True, exist_ok=True)
    problem_dir = repo / "plans" / "thomas" / "problems" / "closure-red-path"
    problem_dir.mkdir(parents=True, exist_ok=True)
    problem_path = problem_dir / "PROBLEM.md"
    entry = (
        "- task_id=closure-red-path; problem=plans/thomas/problems/closure-red-path/PROBLEM.md; "
        "owner=unassigned; status={status}; updated_at=2026-01-01T00:00:00+00:00; summary=test incident\n"
    )
    header = (
        "# PROBLEM for closure-red-path\n\ntask_id: `closure-red-path`\n\n"
        "- Owner: unassigned\n- Status: {status}\n- Updated At: 2026-01-01T00:00:00+00:00\n- Scope: thomas\n\n"
        "## Current Problem\n\ntest incident\n"
    )
    board.write_text(
        "# Test Workboard\n\n## Active Tasks\n\n- none\n\n## Up For Grabs\n\n- none\n\n"
        f"## Task Problems\n\n{entry.format(status='up_for_grabs')}",
        encoding="utf-8",
        newline="\n",
    )
    problem_path.write_text(header.format(status="up_for_grabs"), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial board")
    board.write_text(
        "# Test Workboard\n\n## Active Tasks\n\n- none\n\n## Up For Grabs\n\n- none\n\n"
        f"## Task Problems\n\n{entry.format(status='resolved')}",
        encoding="utf-8",
        newline="\n",
    )
    problem_path.write_text(header.format(status="resolved"), encoding="utf-8")
    _git(repo, "add", "-A")
    return (["--repo-root", str(repo)], repo)


def _dead_ref_violation(tmp_path: Path) -> tuple[list[str], Path]:
    """A dead branch name pushed back via a create-push, with no resurrection
    approval. Uses the real graveyard.py API for the same reason as the
    merge-resurrection fixture above. Uses --ref (not stdin) so this fixture
    never depends on this test process's own inherited stdin -- the shim
    invocation below does not pass an explicit stdin pipe."""
    from scripts.forge import graveyard

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(tmp_path, "init", "-b", "dev", "repo")
    graveyard.record_death(repo, "branch", "old-experiment", "deadbeef", reason="superseded by dev", by="test-suite")
    return (["--repo-root", str(repo), "--ref", "old-experiment"], repo)


def _branch_claim_violation(tmp_path: Path) -> tuple[list[str], Path]:
    """A push CREATING a new branch ref with no live claim recorded for it --
    the shape branch_claim_gate.py exists to catch. Writes a PRESENT-BUT-
    EMPTY docs/ops/branch_claims.json first (via the real branch_claims.py
    API's own on-disk shape, not hand-written) so this exercises real
    enforcement rather than the gate's infrastructure-absence leniency (an
    absent registry file is a loud note-PASS, not a violation -- see
    branch_claim_gate.py's module docstring). Uses --ref (not stdin), same
    reasoning as the dead-ref fixture above: this fixture must never depend
    on this test process's own inherited stdin."""
    from scripts.forge import branch_claims

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(tmp_path, "init", "-b", "dev", "repo")
    claims_path = branch_claims.path(repo)
    claims_path.parent.mkdir(parents=True, exist_ok=True)
    claims_path.write_text('{"version": 1, "records": []}', encoding="utf-8")
    return (["--repo-root", str(repo), "--ref", "unclaimed-red-path"], repo)


def _site_visual_proof_violation(tmp_path: Path) -> tuple[list[str], Path]:
    """A website UI file (apps/site/src/app/**) staged with no visual proof
    bundle at all -- no ui-proof.json, no fresh screenshots, no runtime
    report. This is the shape the gate exists to catch, and it is the fixture
    that closes site-visual-proof-baseline-drift-2026-08-26: that incident's
    forensics proved the *validation* half of this gate was never the
    problem -- a genuinely proof-less UI change was always caught -- the
    failure was in the capture/compare pipeline the gate demands proof from
    (scripts/refresh_site_visual_proof.py false-flagged an unchanged footer
    at ~59% pixel drift from anti-aliasing/scroll-timing noise, not from any
    missing-proof gap this test would exercise). Fixed there; this fixture is
    the missing red-path proof that the gate itself still has teeth."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(tmp_path, "init", "-b", "dev", "repo")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    app_dir = repo / "apps" / "site" / "src" / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "globals.css").write_text("body { color: red; }\n", encoding="utf-8")
    _git(repo, "add", "apps/site/src/app/globals.css")
    return (["--repo-root", str(repo)], repo)


def _untracked_import_violation(tmp_path: Path) -> tuple[list[str], Path]:
    """A committed module importing a file git never learned about.

    The real incident (2026-09-07): four modules under thomas/ were imported by
    committed files and never `git add`-ed. Every working tree that happened to
    hold the files passed every hook; a clean clone of dev died with ImportError
    on the server and on every board command. The fixture reproduces exactly
    that -- importer tracked, imported module present on disk but untracked --
    because a fixture that also staged the module would be green for the wrong
    reason and this gate would go back to being unwatched.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(tmp_path, "init", "-b", "dev", "repo")
    _git(repo, "config", "user.email", "red@example.com")
    _git(repo, "config", "user.name", "Red Path")
    # Inside a real package root: the gate only considers imports whose first
    # segment is one of PACKAGE_ROOTS, so a bare top-level module would be
    # filtered out before resolution and this fixture would pass for the wrong
    # reason. (That filter is a latent blind spot for any NEW top-level package;
    # measured 2026-09-08 as catching nothing extra on this repo today.)
    pkg = repo / "thomas"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "red_path_untracked_helper.py").write_text("VALUE = 1\n", encoding="utf-8")
    (pkg / "importer.py").write_text("from thomas import red_path_untracked_helper\n", encoding="utf-8")
    # Only the importer is tracked. The helper stays untracked -- the whole point.
    _git(repo, "add", "thomas/__init__.py", "thomas/importer.py")
    _git(repo, "commit", "-m", "importer only")
    return (["--repo", str(repo), "--all"], repo)


# RED_PATH_CASES values are (fixture_builder, expected_token): expected_token
# is the string that MUST appear in the gate's combined stdout+stderr when it
# fails, so the parametrized test below cannot pass on a false non-zero exit
# that never actually named the violation. The ratchet in
# test_no_gate_enforces_unwatched.py only reads the dict's keys
# (set(RED_PATH_CASES)), so this shape change does not affect it.
def _workboard_task_plans_violation(tmp_path: Path) -> tuple[list[str], Path]:
    """A task whose Task Plans row names a different owner than its Active Task.

    The board is hand-written and needs no git: in non-staged mode the gate reads
    the board file it is given. --agent is passed explicitly because the gate scopes
    its verdict to the committing agent and otherwise reads THOMAS_AGENT_ID -- run
    under another agent's environment the same board would downgrade to a warning
    and exit 0, so this red path would pass or fail depending on who ran the suite.
    """
    repo = tmp_path / "repo"
    board = repo / "plans" / "thomas" / "WORKBOARD.md"
    board.parent.mkdir(parents=True, exist_ok=True)
    board.write_text(
        "# Test Workboard\n\n"
        "## Agent Claims (Active)\n\n"
        "- agent=agent1; name=Agent One; role=solo; parent=none; scope=src/a.py; "
        "task=task-plans-red-path\n\n"
        "## Active Tasks\n\n"
        "- task_id=task-plans-red-path; agent=agent1; scope=src/a.py; summary=red path; "
        "status=active\n\n"
        "## Issues / Blockers\n\n- none\n\n"
        "## Up For Grabs\n\n- none\n\n"
        "## Task Plans\n\n"
        "- task_id=task-plans-red-path; plan=plans/tasks/task-plans-red-path/PLAN.md; "
        "owner=someone-else; status=in_progress; updated_at=now; summary=red path\n\n"
        "## Task Problems\n\n"
        "- task_id=task-plans-red-path; problem=plans/problems/task-plans-red-path/PROBLEM.md; "
        "owner=agent1; status=in_progress; updated_at=now; summary=red path\n",
        encoding="utf-8",
        newline="\n",
    )
    return (["--workboard", str(board), "--agent", "agent1"], repo)


def _new_repo(tmp_path: Path) -> Path:
    """A fixture git repo with one commit, so `git diff --cached` has a HEAD to
    compare against. The six Agent Verification Protocol gates below all read
    the staged index, and several read HEAD as well (shrinkage compares line
    counts, dependency reads the staged diff) -- an unborn branch would change
    what git reports and make the fixture prove something other than the
    violation it is named for."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(tmp_path, "init", "-b", "dev", "repo")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")
    return repo


def _verification_record_violation(tmp_path: Path) -> tuple[list[str], Path]:
    """Staged code files with NO .git/agent_verification.json at all.

    The record is absent rather than stale or incomplete because absence is the
    one shape that cannot be argued with -- a present-but-bad record exercises
    the validators (_check_freshness/_check_tests_run/_check_regression), which
    are their own branches, while "you staged code and produced no evidence at
    all" is the condition the gate exists for. The count must clear the gate's
    VERIFICATION_THRESHOLD of 3; below it the gate returns a deliberate PASS.

    41 rather than 3 on purpose. This gate never echoes a filename, so the
    staged COUNT is the only fixture-specific string it prints, and the count is
    therefore what the expected_token pins. At 3 files the sentence
    "You staged 3 code files but no verification record exists." is one an
    ordinary small commit could also produce -- so if the --repo-root seam ever
    broke and the gate went back to judging the real Thomas checkout, this red
    path could pass while testing nothing. 41 is a count no real commit is
    likely to be holding at the moment the suite runs.
    """
    repo = _new_repo(tmp_path)
    names = [f"unverified_{i:02d}.py" for i in range(41)]
    for name in names:
        (repo / name).write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", *names)
    return (["--repo-root", str(repo)], repo)


def _commit_scope_violation(tmp_path: Path) -> tuple[list[str], Path]:
    """Sixty staged ADDED .py files -- past the gate's HARD_LIMIT of 50.

    Additions, never moves or removals: _staged_moved_or_removed() subtracts
    every R and D entry on purpose (a deletion hides nothing in volume, and
    counting them blocked honest cleanup -- see that function's comment). A
    fixture built from deletions would therefore be exempt and pass, proving
    nothing. Sixty also clears the hard limit outright rather than the
    20-file warn threshold, so this red path does not depend on the absence of
    a scope_justification in a verification record -- that is a second,
    separate branch.
    """
    repo = _new_repo(tmp_path)
    names = [f"mod_{i:02d}.py" for i in range(60)]
    for name in names:
        (repo / name).write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", *names)
    return (["--repo-root", str(repo)], repo)


def _shrinkage_violation(tmp_path: Path) -> tuple[list[str], Path]:
    """A committed 500-line module re-staged at 80 lines, with no verification
    record to justify it.

    The file must exist in HEAD: _head_line_count() returns None for a new file
    and the gate skips it, so a fixture that only staged a short file would pass
    while looking like a 84%-deletion. The shrinkage is measured HEAD-vs-INDEX,
    not HEAD-vs-worktree, which is why the gutted version is staged rather than
    merely written to disk. No record is written at all, so
    `shrinkage.deletions_justified` is absent -- the shape of a silent gutting
    during "cleanup", which is gap 2, the reason this gate exists.
    """
    repo = _new_repo(tmp_path)
    victim = repo / "gutted_module.py"
    victim.write_text("\n".join(f"line_{i} = {i}" for i in range(500)) + "\n", encoding="utf-8")
    _git(repo, "add", "gutted_module.py")
    _git(repo, "commit", "-m", "add the module at full size")
    victim.write_text("\n".join(f"line_{i} = {i}" for i in range(80)) + "\n", encoding="utf-8")
    _git(repo, "add", "gutted_module.py")
    return (["--repo-root", str(repo)], repo)


def _test_coverage_violation(tmp_path: Path) -> tuple[list[str], Path]:
    """Three staged source files under thomas/ and nothing under tests/.

    The paths must sit under a configured source prefix: _is_source_code()
    requires one of safety_config.source_dirs() (thomas/, scripts/,
    extensions/), so three bare top-level .py files would not count as source at
    all and the fixture would pass for the wrong reason. Nothing doc- or
    config-shaped is staged either: a staged set that is entirely .md/.toml/
    .json trips the gate's docs-only skip before any counting happens.
    """
    repo = _new_repo(tmp_path)
    pkg = repo / "thomas"
    pkg.mkdir()
    names = [
        "thomas/red_path_module_a.py",
        "thomas/red_path_module_b.py",
        "thomas/red_path_module_c.py",
    ]
    for name in names:
        (repo / name).write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", *names)
    return (["--repo-root", str(repo)], repo)


def _dependency_violation(tmp_path: Path) -> tuple[list[str], Path]:
    """A staged pyproject.toml that adds a package, with no verification record
    recording `dependencies_reviewed`.

    pyproject.toml must exist in HEAD and be MODIFIED, not added: the gate reads
    `git diff --cached -- pyproject.toml` and extracts names from `+` lines, so a
    brand-new file would hand it every line of the file (including the table
    headers its filter list does not know) and the fixture would be asserting
    something other than "one new dependency appeared". The added name is
    deliberately not in _extract_new_deps_from_pyproject's exclusion list of
    metadata keys, which is what separates a real dependency addition from a
    version bump or a description edit.
    """
    repo = _new_repo(tmp_path)
    pyproject = repo / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "fixture"\nversion = "0.1.0"\ndependencies = [\n    "aiohttp>=3.9",\n]\n',
        encoding="utf-8",
    )
    _git(repo, "add", "pyproject.toml")
    _git(repo, "commit", "-m", "add pyproject")
    pyproject.write_text(
        '[project]\nname = "fixture"\nversion = "0.1.0"\ndependencies = [\n'
        '    "aiohttp>=3.9",\n    "leftpad>=1.0",\n]\n',
        encoding="utf-8",
    )
    _git(repo, "add", "pyproject.toml")
    return (["--repo-root", str(repo)], repo)


def _frontend_lint_violation(tmp_path: Path) -> tuple[list[str], Path]:
    """A staged apps/ TypeScript file with a genuine type error, plus the
    tsconfig.json the gate looks for and a real TypeScript install to check it
    with. This is the violation shape frontend_lint_gate.py exists to catch
    (gap 4, "frontend code barely covered").
    This was a strict xfail for part of 2026-09-19, because the gate could not
    report the violation on Windows: _find_tsc() returned the EXTENSIONLESS npm
    shim, which CreateProcess cannot execute, and _run_tsc() caught the resulting
    OSError and returned (True, ...) -- turning "I could not run the compiler"
    into a pass. Measured then: the gate printed '"errors": [], "ok": true' while
    tsc.cmd on the same staged file reported TS2322. Both were fixed (prefer the
    .cmd shim; fail closed when the checker will not run) and the fixture was
    promoted here.
    The compiler is junctioned in rather than stubbed: a stub would only prove the
    gate can run a stub. If apps/site has no node_modules, the test skips - an
    honest "not checked" beats a green that checked nothing, which is the precise
    bug this fixture exists to prevent recurring.
    """
    repo = _new_repo(tmp_path)
    app = repo / "apps" / "site"
    (app / "src").mkdir(parents=True)
    real_modules = Path(__file__).resolve().parents[1] / "apps" / "site" / "node_modules"
    if not (real_modules / ".bin").exists():
        pytest.skip("apps/site/node_modules is not installed; there is no compiler to check with")
    link = app / "node_modules"
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(real_modules)], check=True, capture_output=True)
    else:
        link.symlink_to(real_modules, target_is_directory=True)
    (app / "tsconfig.json").write_text(
        '{"compilerOptions":{"noEmit":true,"strict":true,"target":"es2020",'
        '"module":"esnext","moduleResolution":"bundler","skipLibCheck":true},'
        '"include":["src/**/*.ts"]}\n',
        encoding="utf-8",
    )
    (app / "src" / "broken.ts").write_text(
        'export const broken: number = "definitely not a number";\n', encoding="utf-8"
    )
    _git(repo, "add", "apps/site/src/broken.ts", "apps/site/tsconfig.json")
    return (["--repo-root", str(repo)], repo)


RED_PATH_CASES: dict[str, tuple[Callable[[Path], tuple[list[str], Path]], str]] = {
    "monolith_guard.py": (_monolith_violation, "huge_module.py"),
    "merge_resurrection_gate.py": (_merge_resurrection_violation, "old/retired_module.py"),
    "dead_ref_gate.py": (_dead_ref_violation, "old-experiment"),
    "branch_claim_gate.py": (_branch_claim_violation, "unclaimed-red-path"),
    "workboard_evidence_gate.py": (_workboard_evidence_violation, "evidence-red-path"),
    "workboard_task_plans.py": (_workboard_task_plans_violation, "Task Plans owner differs"),
    "problem_closure_gate.py": (_problem_closure_violation, "closure-red-path"),
    "untracked_import_gate.py": (_untracked_import_violation, "red_path_untracked_helper"),
    "site_visual_proof.py": (_site_visual_proof_violation, "apps/site/verification/ui-proof.json"),
    # The 2026-03-19 Agent Verification Protocol gates, wired into commit.py on
    # 2026-09-19. All six hardcoded their repo root and ran git with cwd=ROOT, so
    # they could only ever judge the checkout they live in; each gained the same
    # --repo-root seam monolith_guard.py already had, which is what makes these
    # fixtures possible. frontend_lint_gate.py is deliberately absent -- see
    # test_frontend_lint_gate_has_no_reachable_failure_on_this_toolchain below.
    "verification_record_gate.py": (
        _verification_record_violation,
        "You staged 41 code files but no verification record exists.",
    ),
    "commit_scope_gate.py": (_commit_scope_violation, "Commit touches 60 code files"),
    "shrinkage_gate.py": (_shrinkage_violation, "gutted_module.py"),
    "test_coverage_gate.py": (_test_coverage_violation, "thomas/red_path_module_a.py"),
    "dependency_gate.py": (_dependency_violation, "leftpad"),
    "frontend_lint_gate.py": (_frontend_lint_violation, "broken.ts"),
}


@pytest.mark.parametrize("gate", sorted(RED_PATH_CASES))
def test_every_registered_gate_fails_loudly_on_its_red_path_fixture(gate, tmp_path):
    """Parametrized over sorted(RED_PATH_CASES) so the registry is
    self-executing: a gate can only count as covered by actually running its
    fixture through the real shim, not by merely appearing as a dict key."""
    fixture_builder, expected_token = RED_PATH_CASES[gate]
    args, cwd = fixture_builder(tmp_path)
    proc = run_gate_through_shim(gate, args, cwd)
    combined = proc.stdout + proc.stderr
    assert proc.returncode != 0, f"{gate} exited 0 on a registered violation -- the July disease:\n{combined}"
    assert expected_token in combined, f"{gate} failed but did not name {expected_token!r} in its output:\n{combined}"


def _monolith_violation_precommit_form(tmp_path: Path) -> tuple[list[str], Path]:
    """The invocation form pre-commit actually runs: no --repo-root, only
    --staged-only, cwd = the repo being checked. This is where the July
    defect lived (HEAD's old `parents[1]` default resolved to scripts/forge
    instead of the repo root, so this exact form silently scanned nothing)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(tmp_path, "init", "-b", "dev", "repo")
    big = repo / "huge_module.py"
    big.write_text("\n".join(f"x{i} = {i}" for i in range(1301)) + "\n", encoding="utf-8")
    _git(repo, "add", "huge_module.py")
    return (["--staged-only"], repo)


@pytest.mark.xfail(
    reason=(
        "Default repo-root resolution reads Path(__file__).resolve().parents[3] "
        "-- the monolith_guard.py SCRIPT's own on-disk location, not the process "
        "cwd. Running the pre-commit-form args (--staged-only, no --repo-root) "
        "against a tmp fixture therefore resolves repo_root to the REAL Thomas "
        "checkout, not the fixture, and reports 'Scanned 0 files' instead of "
        "catching the fixture's violation. Verified manually: returncode 0, "
        "'huge_module.py' absent from output, output reads "
        "'Monolith guard OK. Scanned 0 files under .'. This test exists to make "
        "that gap visible rather than silently absent: the pre-commit invocation "
        "form is NOT provably able to catch a violation in a disposable fixture "
        "with this harness, because it never looks at the fixture at all. Only "
        "the explicit --repo-root form (RED_PATH_CASES['monolith_guard.py'], "
        "test_every_registered_gate_fails_loudly_on_its_red_path_fixture) is "
        "covered today. Closing this xfail requires either a relocatable gate "
        "script or a real git-staged fixture inside this actual repo checkout."
    ),
    strict=True,
)
def test_monolith_guard_pre_commit_form_catches_the_fixture_violation(tmp_path):
    args, cwd = _monolith_violation_precommit_form(tmp_path)
    proc = run_gate_through_shim("monolith_guard.py", args, cwd)
    combined = proc.stdout + proc.stderr
    assert proc.returncode != 0, "gate exited 0 on a hard-limit violation:\n" + combined
    assert "huge_module.py" in combined, "gate failed but did not name the violating file:\n" + combined
