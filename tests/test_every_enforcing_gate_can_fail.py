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


# RED_PATH_CASES values are (fixture_builder, expected_token): expected_token
# is the string that MUST appear in the gate's combined stdout+stderr when it
# fails, so the parametrized test below cannot pass on a false non-zero exit
# that never actually named the violation. The ratchet in
# test_no_gate_enforces_unwatched.py only reads the dict's keys
# (set(RED_PATH_CASES)), so this shape change does not affect it.
RED_PATH_CASES: dict[str, tuple[Callable[[Path], tuple[list[str], Path]], str]] = {
    "monolith_guard.py": (_monolith_violation, "huge_module.py"),
    "merge_resurrection_gate.py": (_merge_resurrection_violation, "old/retired_module.py"),
    "dead_ref_gate.py": (_dead_ref_violation, "old-experiment"),
    "branch_claim_gate.py": (_branch_claim_violation, "unclaimed-red-path"),
    "workboard_evidence_gate.py": (_workboard_evidence_violation, "evidence-red-path"),
    "problem_closure_gate.py": (_problem_closure_violation, "closure-red-path"),
    "site_visual_proof.py": (_site_visual_proof_violation, "apps/site/verification/ui-proof.json"),
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
