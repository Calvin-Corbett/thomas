"""A task cannot land as done without evidence: coverage for the phase-1.4
task-4 gate (scripts/forge/gates/workboard_evidence_gate.py).

The gate reads the WORKBOARD.md board DIFF itself (the staged index by
default, `--base`/`--head` for CI) rather than trusting any particular
writer's call path -- see the gate's module docstring, "WHY THIS GATE
EXISTS AS THE NET". Every fixture board below is hand-written text, built
directly with `_write_board`/string edits, never through
`claim_evidence.record_evidence` or `reactivate.set_task_status` -- exactly
to prove that: the gate must catch a done transition regardless of what
wrote it, the way it would have to catch a future writer routed through
`scripts/crew/workboard/issue.py`'s pinned, evidence-blind
`_set_task_status`.

Contracts (task-4-brief.md + the plan's Task 4 section):
1. done-without-evidence staged -> FAIL naming the task.
2. done-with-verified-evidence -> PASS.
3. malformed evidence -> FAIL naming the grammar defect.
4. non-done WORKBOARD edits pass untouched.
5. RED_PATH_CASES entry through the real shim (registered in
   tests/test_every_enforcing_gate_can_fail.py); ratchet green.

Plus, per this phase's design review: attested-pass-with-note,
unavailable-pass-with-note, an already-done-and-unchanged line staying out
of scope, and a hand-crafted board diff proving the gate catches a done
that never went through reactivate.py's evidence plumbing at all (the
issue.py-class bypass this gate exists to net).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts.forge.gates import workboard_evidence_gate as gate

REPO_ROOT = Path(__file__).resolve().parents[1]


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def _head_sha(repo: Path) -> str:
    proc = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
    return proc.stdout.strip()


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(tmp_path, "init", "-b", "dev", "repo")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    return repo


def _board_path(repo: Path) -> Path:
    return repo / "plans" / "thomas" / "WORKBOARD.md"


def _write_board(repo: Path, active_tasks_block: str) -> Path:
    board = _board_path(repo)
    board.parent.mkdir(parents=True, exist_ok=True)
    board.write_text(
        "# Test Workboard\n\n## Active Tasks\n\n" + active_tasks_block + "## Up For Grabs\n\n- none\n",
        encoding="utf-8",
        newline="\n",
    )
    return board


def _active_task_line(task_id: str, *, status: str, summary: str = "do the thing", extra: str = "") -> str:
    line = f"- task_id={task_id}; agent=agent1; scope=foo; summary={summary}; status={status}"
    if extra:
        line += f"; {extra}"
    return line + "\n"


def _commit_all(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)
    return _head_sha(repo)


def _commit_empty(repo: Path, message: str) -> str:
    _git(repo, "commit", "--allow-empty", "-m", message)
    return _head_sha(repo)


def _stage_board(repo: Path) -> None:
    _git(repo, "add", "plans/thomas/WORKBOARD.md")


# ---------------------------------------------------------------------------
# 1. done-without-evidence staged -> FAIL naming the task
# ---------------------------------------------------------------------------


def test_a_done_transition_with_no_evidence_field_fails_naming_the_task(tmp_path):
    repo = _init_repo(tmp_path)
    _write_board(repo, _active_task_line("task-a", status="in_progress"))
    _commit_all(repo, "initial board")
    _write_board(repo, _active_task_line("task-a", status="done"))
    _stage_board(repo)

    result = gate.run_check(repo)

    assert result["ok"] is False
    assert result["done_transitions_checked"] == 1
    [violation] = result["violations"]
    assert violation["classification"] == "missing_evidence"
    assert "task-a" in violation["detail"]


# ---------------------------------------------------------------------------
# 2. done-with-verified-evidence -> PASS
# ---------------------------------------------------------------------------


def test_a_done_transition_with_a_task_bound_ancestor_commit_verifies_and_passes(tmp_path):
    repo = _init_repo(tmp_path)
    _write_board(repo, _active_task_line("task-a", status="in_progress"))
    _commit_all(repo, "initial board")
    sha = _commit_empty(repo, "task-a: land the actual change")
    _write_board(repo, _active_task_line("task-a", status="done", extra=f"evidence=commit:{sha}"))
    _stage_board(repo)

    result = gate.run_check(repo)

    assert result["ok"] is True
    assert result["violations"] == []
    [item] = result["results"]
    assert item["classification"] == "verified"


# ---------------------------------------------------------------------------
# 3. malformed evidence -> FAIL naming the grammar defect
# ---------------------------------------------------------------------------


def test_malformed_evidence_fails_naming_the_grammar_defect(tmp_path):
    repo = _init_repo(tmp_path)
    _write_board(repo, _active_task_line("task-a", status="in_progress"))
    _commit_all(repo, "initial board")
    _write_board(repo, _active_task_line("task-a", status="done", extra="evidence=bogus"))
    _stage_board(repo)

    result = gate.run_check(repo)

    assert result["ok"] is False
    [violation] = result["violations"]
    assert violation["classification"] == "malformed_evidence"
    assert "task-a" in violation["detail"]
    assert "missing a `:` separator" in violation["detail"]


# ---------------------------------------------------------------------------
# 4. non-done WORKBOARD edits pass untouched
# ---------------------------------------------------------------------------


def test_a_non_done_status_edit_passes_untouched(tmp_path):
    repo = _init_repo(tmp_path)
    _write_board(repo, _active_task_line("task-a", status="claimed"))
    _commit_all(repo, "initial board")
    _write_board(repo, _active_task_line("task-a", status="in_progress"))
    _stage_board(repo)

    result = gate.run_check(repo)

    assert result["ok"] is True
    assert result["active_tasks_checked"] == 1
    assert result["done_transitions_checked"] == 0
    assert result["violations"] == []


# ---------------------------------------------------------------------------
# attested-pass-with-note: an unbound-but-landed commit attests, not
# verifies, and still passes the gate (attested is recorded-not-proven --
# the gate is not the place to hard-refuse what the transition tooling
# already accepted).
# ---------------------------------------------------------------------------


def test_a_landed_but_unbound_commit_attests_and_passes_with_a_printed_note(tmp_path):
    repo = _init_repo(tmp_path)
    _write_board(repo, _active_task_line("task-a", status="in_progress"))
    _commit_all(repo, "initial board")
    sha = _commit_empty(repo, "generic housekeeping change, no task id here")
    _write_board(repo, _active_task_line("task-a", status="done", extra=f"evidence=commit:{sha}"))
    _stage_board(repo)

    result = gate.run_check(repo)

    assert result["ok"] is True
    assert result["attested_count"] == 1
    [item] = result["results"]
    assert item["classification"] == "attested"
    assert "not bound to this task" in item["reason"]


# ---------------------------------------------------------------------------
# unavailable-pass-with-note: run-kind evidence with no --run-store-db
# never ran a real check, so it passes (never a refusal on absent
# infrastructure) with a printed note, and is never silently green either
# (the note names exactly why).
# ---------------------------------------------------------------------------


def test_run_evidence_with_no_run_store_db_is_unavailable_not_a_failure(tmp_path):
    repo = _init_repo(tmp_path)
    _write_board(repo, _active_task_line("task-a", status="in_progress"))
    _commit_all(repo, "initial board")
    _write_board(
        repo,
        _active_task_line("task-a", status="done", extra="evidence=run:some-run-id:0-1"),
    )
    _stage_board(repo)

    result = gate.run_check(repo, run_store_db=None)

    assert result["ok"] is True
    assert result["unavailable_count"] == 1
    [item] = result["results"]
    assert item["classification"] == "unavailable"
    assert item["reason_code"] == "db_path_required"


def test_the_printed_unavailable_note_names_the_reason_code_not_just_json(tmp_path, monkeypatch, capsys):
    """Phase 2 batch 1, recon #7b: gates.yml's CI job never passes
    --run-store-db (the run_store db is a per-machine data file, never a repo
    artifact -- see gates.yml's comment on this job). That makes the
    human-readable console note, not just the --json payload, the thing a
    human actually reads in CI output -- so it must name the machine
    reason_code, not just prose that reads the same for every unavailable
    cause.
    """
    repo = _init_repo(tmp_path)
    _write_board(repo, _active_task_line("task-a", status="in_progress"))
    _commit_all(repo, "initial board")
    _write_board(
        repo,
        _active_task_line("task-a", status="done", extra="evidence=run:some-run-id:0-1"),
    )
    _stage_board(repo)
    monkeypatch.setattr(sys, "argv", ["workboard_evidence_gate.py", "--repo-root", str(repo)])

    rc = gate.main()

    out = capsys.readouterr().out
    assert rc == 0
    assert "UNAVAILABLE (db_path_required" in out


# ---------------------------------------------------------------------------
# already-done-unchanged is out of scope: a line that was ALREADY done on
# the other side of the diff, unchanged, is not re-litigated here -- that
# is the expiry sweep's job (claim_evidence_sweep.py), not this gate's.
# ---------------------------------------------------------------------------


def test_a_line_already_done_and_unchanged_is_out_of_scope(tmp_path):
    repo = _init_repo(tmp_path)
    # Landed with NO evidence at all -- a legacy done that predates this
    # gate. Still must not be re-flagged just because it lacks evidence:
    # its status never transitioned in THIS diff.
    _write_board(repo, _active_task_line("task-a", status="done"))
    _commit_all(repo, "initial board (legacy done, no evidence)")
    _write_board(repo, _active_task_line("task-a", status="done", summary="do the thing (typo fixed)"))
    _stage_board(repo)

    result = gate.run_check(repo)

    assert result["ok"] is True
    assert result["active_tasks_checked"] == 1
    assert result["done_transitions_checked"] == 0


# ---------------------------------------------------------------------------
# The issue.py-class bypass simulation: a done written by directly flipping
# the `status=` field in place -- exactly the operation
# scripts/crew/workboard/issue.py's PINNED `_set_task_status(lines, *,
# task_id, status)` performs, with no evidence plumbing anywhere in the
# path. This fixture never calls claim_evidence.record_evidence or
# reactivate.set_task_status -- proving the gate catches the transition
# from the board diff alone, regardless of which writer produced it (see
# the gate's module docstring, "WHY THIS GATE EXISTS AS THE NET").
# ---------------------------------------------------------------------------


def test_a_hand_crafted_status_flip_with_no_evidence_infrastructure_is_caught(tmp_path):
    repo = _init_repo(tmp_path)
    _write_board(repo, _active_task_line("task-a", status="claimed"))
    _commit_all(repo, "initial board")

    board = _board_path(repo)
    original = board.read_text(encoding="utf-8")
    # A raw field flip, not a rewrite through any workboard/evidence module
    # -- this is what a parallel writer with no evidence awareness would
    # produce.
    flipped = original.replace("status=claimed", "status=done")
    assert flipped != original
    board.write_text(flipped, encoding="utf-8", newline="\n")
    _stage_board(repo)

    result = gate.run_check(repo)

    assert result["ok"] is False
    [violation] = result["violations"]
    assert violation["classification"] == "missing_evidence"
    assert "task-a" in violation["detail"]


# ---------------------------------------------------------------------------
# Diff-range mode (the CI form): the same check over base..head instead of
# the staged index.
# ---------------------------------------------------------------------------


def test_diff_range_mode_catches_the_same_missing_evidence_violation(tmp_path):
    repo = _init_repo(tmp_path)
    _write_board(repo, _active_task_line("task-a", status="in_progress"))
    base_sha = _commit_all(repo, "initial board")
    _write_board(repo, _active_task_line("task-a", status="done"))
    head_sha = _commit_all(repo, "flip to done with no evidence")

    result = gate.run_check(repo, base=base_sha, head=head_sha)

    assert result["mode"] == "diff-range"
    assert result["ok"] is False
    [violation] = result["violations"]
    assert violation["classification"] == "missing_evidence"
    assert "task-a" in violation["detail"]


# ---------------------------------------------------------------------------
# 5. RED_PATH_CASES entry through the real shim; the coverage ratchet must
# stay green with no baseline delta.
# ---------------------------------------------------------------------------


def test_the_gate_is_registered_in_red_path_cases_and_fails_through_the_real_shim(tmp_path):
    from tests.test_every_enforcing_gate_can_fail import RED_PATH_CASES, run_gate_through_shim

    assert "workboard_evidence_gate.py" in RED_PATH_CASES
    fixture_builder, expected_token = RED_PATH_CASES["workboard_evidence_gate.py"]
    args, cwd = fixture_builder(tmp_path)

    proc = run_gate_through_shim("workboard_evidence_gate.py", args, cwd)

    combined = proc.stdout + proc.stderr
    assert proc.returncode != 0, f"gate exited 0 on a registered violation:\n{combined}"
    assert expected_token in combined, f"gate failed but did not name {expected_token!r}:\n{combined}"


def test_the_gate_is_not_in_the_selftest_debt_baseline(tmp_path):
    """The ratchet's baseline may only shrink -- a NEW enforcing gate must
    never be grandfathered into it. Direct regression coverage for this one
    gate, independent of tests/test_no_gate_enforces_unwatched.py's
    repo-wide ratchet assertion."""
    import json

    baseline_path = REPO_ROOT / "tests" / "gate_selftest_baseline.json"
    baseline = set(json.loads(baseline_path.read_text(encoding="utf-8")))
    assert "workboard_evidence_gate.py" not in baseline


# ---------------------------------------------------------------------------
# The runtime-protection disable flag short-circuits BEFORE any board-diff
# work happens -- covered directly, the way sibling gates are covered in
# tests/test_enforcement_bypass_resistance.py. Kept HERE instead of there:
# that file is already 976 lines, over monolith_guard's unbaselined 800-line
# soft limit, and is not this gate's own file -- adding to it would require
# baselining docs/monolith_guard_baseline.json, a protected file
# (agent_safety.toml) this session has no explicit user approval to touch.
# This gate's own test file is the honest, unblocked home for the same
# coverage.
# ---------------------------------------------------------------------------


def test_runtime_protection_disabled_short_circuits_before_any_git_or_board_work(monkeypatch, capsys):
    monkeypatch.setattr(gate, "_runtime_protection_disabled", lambda: True)

    rc = gate.main()

    out = capsys.readouterr().out
    assert rc == 0
    assert "runtime protection disabled" in out.lower()
