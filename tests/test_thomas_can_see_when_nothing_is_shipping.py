"""Thomas can see the fleet stop.

Every guard in scripts/forge/gates watches for too much - too many files in a
commit, too many lines added to one file, too many lines in one module. On
2026-09-02 five agents held claims and landed zero commits for twelve hours,
and every guard read clean the entire time. A jammed fleet scored better than a
working one, because nothing in Thomas measured absence.

Each test drives a throwaway git repo and proves a detector can go RED, and its
pair proves it stays quiet when the same situation is healthy. A detector that
only ever reports zero is not evidence of health; these show what makes each
one fire.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.forge import fleet_stall  # noqa: E402

CLAIMS = (
    "- agent=one; name=One; role=solo; parent=none; scope=a.py; task=T1\n"
    "- agent=two; name=Two; role=solo; parent=none; scope=b.py; task=T2\n"
)
LONG_AGO = "2020-01-01T00:00:00Z"


def _run(repo: Path, *args: str, when: str | None = None) -> None:
    env = dict(os.environ)
    if when:
        env["GIT_COMMITTER_DATE"] = when
        env["GIT_AUTHOR_DATE"] = when
    subprocess.run(("git", *args), cwd=str(repo), capture_output=True, text=True, check=True, env=env)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repo whose only commit is far outside any sane stall window."""
    _run(tmp_path, "init", "-q")
    _run(tmp_path, "config", "user.email", "t@example.invalid")
    _run(tmp_path, "config", "user.name", "Test")
    (tmp_path / "seed.txt").write_text("seed\n", encoding="utf-8")
    _run(tmp_path, "add", "seed.txt")
    _run(tmp_path, "commit", "-q", "-m", "seed", when=LONG_AGO)
    return tmp_path


def _board(repo: Path, body: str) -> Path:
    path = repo / "WORKBOARD.md"
    path.write_text("## Agent Claims\n\n" + body, encoding="utf-8")
    return path


def test_a_fleet_holding_claims_and_landing_nothing_is_reported(repo: Path) -> None:
    board = _board(repo, CLAIMS)
    findings = fleet_stall.find_stall(board.read_text(encoding="utf-8"), hours=8, repo=repo)
    assert len(findings) == 1, "two agents hold scope and the only commit is from 2020"
    assert "0 commits landed in 8h" in findings[0]
    assert "`one`" in findings[0] and "`two`" in findings[0], "the report names who is holding scope"


def test_a_fleet_that_is_shipping_is_quiet(repo: Path) -> None:
    board = _board(repo, CLAIMS)
    (repo / "shipped.txt").write_text("x\n", encoding="utf-8")
    _run(repo, "add", "shipped.txt")
    _run(repo, "commit", "-q", "-m", "shipped something")
    assert fleet_stall.find_stall(board.read_text(encoding="utf-8"), hours=8, repo=repo) == []


def test_a_board_with_no_claims_is_not_called_a_stall(repo: Path) -> None:
    """Nobody holding scope is idle, not stalled - it must not cry wolf."""
    board = _board(repo, "- none\n")
    assert fleet_stall.find_stall(board.read_text(encoding="utf-8"), hours=8, repo=repo) == []


def test_an_untracked_gate_is_named_because_it_still_gates(repo: Path) -> None:
    gates = repo / "gates"
    gates.mkdir()
    (gates / "landed_gate.py").write_text("# committed\n", encoding="utf-8")
    _run(repo, "add", "gates/landed_gate.py")
    _run(repo, "commit", "-q", "-m", "add landed gate", when=LONG_AGO)
    # A distinct name on purpose: "reviewed_gate.py" is a substring of
    # "unreviewed_gate.py", so the negative assertion below could never hold.
    (gates / "draft_gate.py").write_text("# never committed\n", encoding="utf-8")

    joined = "\n".join(fleet_stall.find_unversioned_tooling(repo=repo, gate_dir=gates))
    assert "draft_gate.py" in joined, "an untracked gate that still gates must be named"
    assert "landed_gate.py" not in joined, "a committed gate is not a finding"


def test_a_commit_tool_with_uncommitted_edits_is_named(repo: Path) -> None:
    tool = repo / "scripts" / "crew" / "brief" / "commit.py"
    tool.parent.mkdir(parents=True)
    tool.write_text("# v1\n", encoding="utf-8")
    _run(repo, "add", "scripts/crew/brief/commit.py")
    _run(repo, "commit", "-q", "-m", "add commit tool", when=LONG_AGO)
    gates = repo / "gates"
    gates.mkdir()

    assert fleet_stall.find_unversioned_tooling(repo=repo, gate_dir=gates) == [], "committed and clean is quiet"

    tool.write_text("# v2, in flight\n", encoding="utf-8")
    findings = fleet_stall.find_unversioned_tooling(repo=repo, gate_dir=gates)
    assert any("uncommitted-modified" in f and "commit.py" in f for f in findings)


def test_an_untracked_plan_is_named_because_the_gate_reads_the_index(repo: Path) -> None:
    """The bootstrap paradox: the commit that would track the plan is refused."""
    plan_dir = repo / "plans" / "t" / "T1"
    plan_dir.mkdir(parents=True)
    (plan_dir / "PLAN.md").write_text("# PLAN for T1\n", encoding="utf-8")
    row = (
        "- task_id=T1; plan=plans/t/T1/PLAN.md; owner=one; status=in_progress; "
        "updated_at=2026-09-03T12:00:00+00:00; summary=T1\n"
    )
    findings = fleet_stall.find_untracked_plans(row, repo=repo)
    assert len(findings) == 1 and "T1" in findings[0]

    _run(repo, "add", "plans/t/T1/PLAN.md")
    _run(repo, "commit", "-q", "-m", "track plan", when=LONG_AGO)
    assert fleet_stall.find_untracked_plans(row, repo=repo) == [], "a tracked plan is not a finding"


def test_a_quiet_report_prints_an_honest_zero_on_every_line() -> None:
    report = fleet_stall.Report(hours=8)
    assert fleet_stall.render(report).splitlines() == [
        "STALL: none",
        "UNVERSIONED TOOLING: none",
        "UNTRACKED PLANS: none",
    ]
    assert report.quiet is True


def test_a_missing_workboard_says_why_instead_of_reporting_clean(tmp_path: Path) -> None:
    """An instrument that could not read anything must not report health."""
    report = fleet_stall.build_report(tmp_path / "absent.md", hours=8)
    assert report.quiet is False
    assert report.stall and "unavailable" in report.stall[0]


def test_the_watcher_never_refuses_a_caller(repo: Path) -> None:
    """It reports. A detector that could block a commit joins the problem."""
    board = _board(repo, CLAIMS)
    proc = subprocess.run(
        (sys.executable, str(Path(fleet_stall.__file__)), "--workboard", str(board), "--json"),
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, "the watcher must never fail a caller"
    assert '"quiet"' in proc.stdout
