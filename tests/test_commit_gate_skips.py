"""A gate is skipped only when its own source says it cannot refuse the selection.

scripts/crew/brief/gate_skips.py leaves out workboard_evidence and problem_closure when the selection cannot reach what
they read. Each test here runs the REAL gate (run_check in staged mode, in a tiny real git repo) next to the skip
decision, so a skip rule that drifts from the gate shows up as a refusal the skip would have hidden.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.crew.brief import gate_skips
from scripts.forge.gates import problem_closure_gate as closure_gate
from scripts.forge.gates import workboard_evidence_gate as evidence_gate

BOARD = gate_skips.BOARD


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(tmp_path, "init", "-q", "-b", "dev", "repo")
    _git(repo, "config", "user.name", "T")
    _git(repo, "config", "user.email", "t@example.invalid")
    return repo


def _write_board(repo: Path, *, task_status: str, problems: list[str]) -> None:
    board = repo / BOARD
    board.parent.mkdir(parents=True, exist_ok=True)
    board.write_text(
        "# Test Workboard\n\n## Active Tasks\n\n"
        f"- task_id=task-a; agent=agent1; scope=foo; summary=s; status={task_status}\n\n"
        "## Up For Grabs\n\n- none\n\n## Task Problems\n\n" + ("\n".join(problems) if problems else "- none") + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _problem_entry(task_id: str, path: str, status: str) -> str:
    return (
        f"- task_id={task_id}; problem={path}; owner=unassigned; status={status}; "
        "updated_at=2026-01-01T00:00:00+00:00; summary=incident"
    )


def _write_problem(repo: Path, rel: str, task_id: str, *, status: str, closure: str | None = None) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    closure_line = f"- closure: {closure}\n" if closure else ""
    path.write_text(
        f"# PROBLEM for {task_id}\n\ntask_id: `{task_id}`\n\n- Owner: unassigned\n- Status: {status}\n"
        f"- Updated At: 2026-01-01T00:00:00+00:00\n- Scope: thomas\n{closure_line}\n## Current Problem\n\nx\n",
        encoding="utf-8",
    )


def _head_board(repo: Path) -> str:
    return _git(repo, "show", f"HEAD:{BOARD}")


def _standing_repo(tmp_path: Path) -> Path:
    """HEAD already holds a done task with no evidence and a resolved incident whose closure resolves to nothing:
    standing facts that neither gate looks at again unless something about them changes."""
    repo = _repo(tmp_path)
    _write_board(
        repo,
        task_status="done",
        problems=[_problem_entry("inc-1", "plans/thomas/problems/inc-1/PROBLEM.md", "resolved")],
    )
    _write_problem(repo, "plans/thomas/problems/inc-1/PROBLEM.md", "inc-1", status="resolved", closure="tombstone:nope")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("x = 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    return repo


def test_when_nothing_about_the_board_is_selected_both_gates_pass_and_both_are_skipped(tmp_path: Path) -> None:
    repo = _standing_repo(tmp_path)
    (repo / "src" / "app.py").write_text("x = 2\n")
    _git(repo, "add", "src/app.py")
    assert evidence_gate.run_check(repo)["ok"] is True
    assert closure_gate.run_check(repo)["ok"] is True
    skips = gate_skips.provable_noops(["src/app.py"], lambda: _head_board(repo))
    assert set(skips) == {"workboard_evidence", "problem_closure"}


def test_a_selected_board_turns_both_skips_off_and_the_evidence_gate_does_refuse(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write_board(repo, task_status="in_progress", problems=[])
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    _write_board(repo, task_status="done", problems=[])  # a done with no evidence
    _git(repo, "add", BOARD)
    assert evidence_gate.run_check(repo)["ok"] is False
    assert gate_skips.provable_noops([BOARD], lambda: _head_board(repo)) == {}
    assert gate_skips.provable_noops([BOARD.upper()], lambda: "") == {}  # path case does not hide the board


def test_a_selected_problem_file_keeps_the_closure_gate_and_it_does_refuse(tmp_path: Path) -> None:
    repo = _standing_repo(tmp_path)
    rel = "plans/thomas/problems/inc-2/PROBLEM.md"
    _write_problem(repo, rel, "inc-2", status="in_progress")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "open incident")
    _write_problem(repo, rel, "inc-2", status="resolved")  # resolved with no closure line
    _git(repo, "add", rel)
    assert closure_gate.run_check(repo)["ok"] is False
    skips = gate_skips.provable_noops([rel], lambda: _head_board(repo))
    assert "problem_closure" not in skips
    assert "workboard_evidence" in skips  # the board itself is not selected


def test_a_board_entry_that_names_an_unusual_problem_file_keeps_the_closure_gate(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    odd = "docs/notes/INCIDENT.md"
    _write_board(repo, task_status="in_progress", problems=[_problem_entry("inc-9", odd, "in_progress")])
    _write_problem(repo, odd, "inc-9", status="in_progress")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    _write_problem(repo, odd, "inc-9", status="resolved")  # resolved, no closure, in a file nothing special names
    _git(repo, "add", odd)
    assert closure_gate.run_check(repo)["ok"] is False
    assert "problem_closure" not in gate_skips.provable_noops([odd], lambda: _head_board(repo))


def test_the_board_is_read_only_when_the_answer_needs_it() -> None:
    reads: list[int] = []

    def board() -> str:
        reads.append(1)
        return ""

    gate_skips.provable_noops([BOARD], board)
    assert reads == []
    gate_skips.provable_noops(["src/a.py"], board)
    assert reads == [1]


def test_problem_paths_are_read_loosely_so_the_skip_errs_toward_running() -> None:
    text = (
        "- task_id=a; problem=`plans\\thomas\\problems\\A\\PROBLEM.md`; owner=x\n"
        "- task_id=b; Problem = docs/b.md ; owner=y\n"
        "- task_id=c; summary=no problem field here\n"
    )
    found = gate_skips.problem_paths(text)
    assert "plans/thomas/problems/a/problem.md" in found
    assert "docs/b.md" in found
    assert "" not in found
