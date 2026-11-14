"""Review fixes to the landing (scripts/crew/brief/commit_attempts.py): the tree that lands is the tree the gates judged, a
neighbour that changed the policy makes the kept gate judge again, a gate left out is named, a pause before the rebase, the
switch back to the old behaviour.

Companion to tests/test_commit_attempts.py. The neighbour is real (a commit made with git plumbing, from inside a gate), and
the gates are `python -c` programs that log what they ran and which index content they were shown.
"""

from __future__ import annotations

import types
from pathlib import Path

import pytest
from scripts.crew.brief import commit_attempts, gate_runner, gate_slots

from tests.commit_lane_support import PY, Lane, git, make_lane, mod

ELSE = 'print("edited while the landing was in flight")\n'


@pytest.fixture
def lane(tmp_path: Path, monkeypatch) -> Lane:
    monkeypatch.setenv(gate_runner.WORKERS_ENV, "1")  # serial order: what each test reads off the log is deterministic
    monkeypatch.setenv(commit_attempts.REBASE_JITTER_ENV, "0")
    monkeypatch.delenv("THOMAS_COMMIT_BASE", raising=False)
    monkeypatch.delenv(gate_runner.LEGACY_ENV, raising=False)
    return make_lane(tmp_path)


def _sees_the_index(lane: Lane, name: str) -> tuple[str, ...]:
    """A gate that logs the content of src/app.py as the temporary index holds it."""
    seen = lane.root / f"{name}.seen"
    return lane.logging(
        name,
        "import subprocess",
        "text = subprocess.run(['git', 'show', ':src/app.py'], capture_output=True, text=True).stdout",
        f"open({str(seen)!r}, 'a').write(text.replace(chr(10), '~') + chr(10))",
    )


def _seen(lane: Lane, name: str) -> list[str]:
    path = lane.root / f"{name}.seen"
    return path.read_text().splitlines() if path.exists() else []


def _edit_on_run(lane: Lane, run_number: int, *extra_lines: str) -> list[str]:
    """Lines for a gate that, on its `run_number`th run (counting from 0), lands a neighbour AND rewrites src/app.py."""
    counter = lane.root / "editor.count"
    return [
        "import pathlib, subprocess, sys",
        f"c = pathlib.Path({str(counter)!r}); n = int(c.read_text()) if c.exists() else 0; c.write_text(str(n + 1))",
        f"if n == {run_number}:",
        f"    subprocess.run([sys.executable, {str(lane.neighbour)!r}, {str(lane.repo)!r}, 'other/n%d.txt' % n, 'x'], check=True, capture_output=True)",
        f"    open({str(lane.repo / 'src' / 'app.py')!r}, 'w').write({ELSE!r})",
        *extra_lines,
    ]


def test_a_kept_pass_stands_when_a_neighbour_lands_elsewhere_and_nothing_else_changed(lane: Lane) -> None:
    gates = (
        ("exception_handler", _sees_the_index(lane, "exception_handler")),
        ("mover", lane.logging("mover", *lane.lands_a_neighbour())),
    )
    result = lane.land(gates)
    assert result.ok is True, (result.blocker_class, result.message, result.gate_output)
    assert lane.ran().count("exception_handler") == 1 and lane.ran().count("mover") == 2


def test_a_selected_file_edited_while_the_landing_rebases_is_judged_again_and_that_is_what_lands(lane: Lane) -> None:
    # Review finding F1: the kept pass judged the old bytes; the commit holds the new ones.
    gates = (
        ("exception_handler", _sees_the_index(lane, "exception_handler")),
        ("mover", lane.logging("mover", *_edit_on_run(lane, 0))),
    )
    result = lane.land(gates)
    assert result.ok is True, (result.blocker_class, result.message, result.gate_output)
    assert lane.ran().count("exception_handler") == 2, "a pass for older bytes was kept"
    seen = _seen(lane, "exception_handler")
    assert seen == ['print("changed")~', 'print("edited while the landing was in flight")~']
    assert git(lane.repo, "show", f"{result.commit_sha}:src/app.py") + "\n" == ELSE  # judged == landed


def test_a_pass_from_an_earlier_attempt_is_not_trusted_after_a_later_edit(lane: Lane) -> None:
    # Review finding F2: an attempt that does not run the gate must not let its older pass outlive a later change.
    # Attempt 1: the gate passes, then a refusing gate moves the tip. Attempt 2: the gate's pass stands (nothing changed),
    # then the refusing gate moves the tip again AND edits the file. Attempt 3 must judge the gate again.
    counter = lane.root / "refuser.count"
    refuser = [
        "import pathlib, subprocess, sys",
        f"c = pathlib.Path({str(counter)!r}); n = int(c.read_text()) if c.exists() else 0; c.write_text(str(n + 1))",
        "if n < 2:",
        f"    subprocess.run([sys.executable, {str(lane.neighbour)!r}, {str(lane.repo)!r}, 'other/n%d.txt' % n, 'x'], check=True, capture_output=True)",
        f"    if n == 1: open({str(lane.repo / 'src' / 'app.py')!r}, 'w').write({ELSE!r})",
        "    print('refused ' + str(n)); sys.exit(1)",
    ]
    gates = (
        ("exception_handler", _sees_the_index(lane, "exception_handler")),
        ("refuser", lane.logging("refuser", *refuser)),
    )
    result = lane.land(gates)
    assert result.ok is True, (result.blocker_class, result.message, result.gate_output)
    assert lane.ran() == ["exception_handler", "refuser", "refuser", "exception_handler", "refuser"]
    assert _seen(lane, "exception_handler")[-1] == 'print("edited while the landing was in flight")~'


def test_a_neighbour_that_changed_the_safety_policy_makes_the_kept_gate_judge_again(lane: Lane) -> None:
    # Review finding: agent_safety.toml is not a selected path, so the old rule kept the pass across its change.
    policy = lane.repo / "agent_safety.toml"
    gates = (
        ("exception_handler", lane.logging("exception_handler")),
        (
            "mover",
            lane.logging("mover", *lane.lands_a_neighbour(), f"open({str(policy)!r}, 'w').write('[exceptions]\\n')"),
        ),
    )
    assert lane.land(gates).ok is True
    assert lane.ran().count("exception_handler") == 2


def test_a_pass_from_a_gate_that_ran_while_the_tip_moved_is_not_kept(lane: Lane) -> None:
    # The kept gate runs AFTER the one that moves the tip, so its own run is bracketed by a tip that is not its base.
    gates = (
        ("mover", lane.logging("mover", *lane.lands_a_neighbour())),
        ("exception_handler", lane.logging("exception_handler")),
    )
    assert lane.land(gates).ok is True
    assert lane.ran() == ["mover", "exception_handler", "mover", "exception_handler"]


def test_the_process_scan_pass_is_still_reused_inside_the_landing(lane: Lane) -> None:
    gates = (
        ("active_folder_guard", lane.logging("active_folder_guard")),
        ("mover", lane.logging("mover", *lane.lands_a_neighbour())),
    )
    assert lane.land(gates).ok is True
    assert lane.ran().count("active_folder_guard") == 1 and lane.ran().count("mover") == 2


def test_a_gate_left_out_for_being_unreviewed_is_named_in_the_result(lane: Lane) -> None:
    # Review finding: the sentence was built for every landing and dropped. It is the result's gate_output now.
    (lane.repo / "scripts").mkdir()
    (lane.repo / "scripts" / "ghost_gate.py").write_text(
        "raise SystemExit(1)\n", encoding="utf-8"
    )  # untracked, refuses
    gates = (("ghost", (PY, "scripts/ghost_gate.py")), ("quiet", lane.logging("quiet")))
    note = "skipped unreviewed gate(s), commit them to restore: ghost (scripts/ghost_gate.py)"
    dry = lane.land(gates, dry_run=True)
    assert dry.ok is True and dry.gate_output == note
    result = lane.land(gates)
    assert result.ok is True, (result.blocker_class, result.message, result.gate_output)
    assert result.gate_output == note
    assert result.message == "scoped agent commit created"  # the message itself is as it was


def test_a_landing_that_skips_nothing_has_no_gate_output(lane: Lane) -> None:
    result = lane.land((("quiet", lane.logging("quiet")),))
    assert result.ok is True and result.gate_output is None


def test_a_tracked_gate_registered_under_another_spelling_still_runs_and_still_refuses(lane: Lane) -> None:
    # Review finding C3: "./scripts/gate.py" read as untracked, so a tracked gate that refuses was silently left out.
    (lane.repo / "scripts").mkdir()
    (lane.repo / "scripts" / "gate.py").write_text("print('no'); raise SystemExit(1)\n", encoding="utf-8")
    git(lane.repo, "add", "scripts/gate.py")
    git(lane.repo, "commit", "-qm", "a gate")
    for spelling in ("scripts/gate.py", "./scripts/gate.py", "scripts//gate.py", "scripts/../scripts/gate.py"):
        result = lane.land((("tracked", (PY, spelling)),), dry_run=True)
        assert (result.ok, result.blocker_class) == (False, "local_gate_failed"), spelling


def test_the_rebase_is_made_onto_the_tip_as_it_is_after_the_pause_not_before_it(lane: Lane, monkeypatch) -> None:
    # A pause long enough for another landing must not mean rebasing onto a tip that is already old.
    def pause_while_another_agent_lands() -> None:
        lane.neighbour_lands("other/during-the-pause.txt")

    monkeypatch.setattr(commit_attempts, "_rebase_pause", pause_while_another_agent_lands)
    result = lane.land((("mover", lane.logging("mover", *lane.lands_a_neighbour())),))
    assert result.ok is True, (result.blocker_class, result.message)
    assert lane.subjects() == [
        "feat: land",
        "neighbour lands other/during-the-pause.txt",
        "neighbour lands other/n0.txt",
        "init",
    ]
    assert lane.ran() == ["mover", "mover"]  # one rebase, onto the newest tip


def test_the_pause_is_random_bounded_and_can_be_switched_off(monkeypatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr(commit_attempts, "time", types.SimpleNamespace(sleep=slept.append))
    commit_attempts._rebase_pause({commit_attempts.REBASE_JITTER_ENV: "0"})
    commit_attempts._rebase_pause({commit_attempts.REBASE_JITTER_ENV: "-1"})
    commit_attempts._rebase_pause({commit_attempts.REBASE_JITTER_ENV: "nan"})
    commit_attempts._rebase_pause({commit_attempts.REBASE_JITTER_ENV: "inf"})
    assert slept == []
    for _ in range(40):
        commit_attempts._rebase_pause({commit_attempts.REBASE_JITTER_ENV: "0.5"})
    assert len(slept) == 40 and all(0.0 <= s <= 0.5 for s in slept) and len(set(slept)) > 1
    slept.clear()
    for env in ({}, {commit_attempts.REBASE_JITTER_ENV: "soon"}):  # the default, bounded
        commit_attempts._rebase_pause(env)
    assert len(slept) == 2 and all(0.0 <= s <= commit_attempts.DEFAULT_REBASE_JITTER for s in slept)
    slept.clear()
    for _ in range(40):
        commit_attempts._rebase_pause({commit_attempts.REBASE_JITTER_ENV: "99999"})
    assert max(slept) <= commit_attempts.MAX_REBASE_JITTER


def test_legacy_mode_has_one_attempt_skips_nothing_and_reuses_nothing(lane: Lane, monkeypatch) -> None:
    monkeypatch.setenv(gate_runner.LEGACY_ENV, "1")
    before = lane.head()
    gates = (
        ("workboard_evidence", lane.logging("workboard_evidence")),  # a proven no-op, left out unless legacy
        ("problem_closure", lane.logging("problem_closure")),
        ("mover", lane.logging("mover", *lane.lands_a_neighbour())),
    )
    result = lane.land(gates)
    assert (result.ok, result.blocker_class) == (False, "branch_race")  # the old tool: no rebase
    assert lane.ran() == ["workboard_evidence", "problem_closure", "mover"]
    assert "feat: land" not in lane.subjects() and lane.head() != before  # the neighbour's commit, nothing of ours


def test_legacy_mode_reports_a_refusal_from_a_moving_tip_at_once_as_the_old_tool_did(lane: Lane, monkeypatch) -> None:
    monkeypatch.setenv(gate_runner.LEGACY_ENV, "1")
    result = lane.land((("judge", lane.logging("judge", *lane.lands_a_neighbour(fail=True))),))
    assert (result.ok, result.blocker_class, result.gate_name) == (False, "local_gate_failed", "judge")
    assert result.message == "local gate failed: judge" and lane.ran() == ["judge"]


def test_a_landing_without_a_rebase_is_unchanged_by_all_of_this(lane: Lane) -> None:
    result = lane.land((("exception_handler", lane.logging("exception_handler")), ("quiet", lane.logging("quiet"))))
    assert result.ok is True and lane.ran() == ["exception_handler", "quiet"]
    assert mod._current_head(lane.repo) == result.commit_sha


def test_pooled_gates_of_a_landing_take_the_machine_wide_slots(lane: Lane, monkeypatch, tmp_path: Path) -> None:
    folder = tmp_path / "slot-files"
    gates = (("a", lane.logging("a")), ("b", lane.logging("b")), ("c", lane.logging("c")))
    monkeypatch.setenv(gate_slots.DIR_ENV, str(folder))
    monkeypatch.setenv(gate_slots.SLOTS_ENV, "2")
    monkeypatch.setenv(gate_runner.WORKERS_ENV, "2")
    assert lane.land(gates, dry_run=True).ok is True
    assert sorted(f.name for f in (folder / "thomas-gate-slots").iterdir()), "pooled gates ran without taking a slot"


def test_one_gate_at_a_time_and_the_switched_off_limit_take_no_slot(lane: Lane, monkeypatch, tmp_path: Path) -> None:
    folder = tmp_path / "slot-files"
    gates = (("a", lane.logging("a")), ("b", lane.logging("b")))
    monkeypatch.setenv(gate_slots.DIR_ENV, str(folder))
    monkeypatch.setenv(gate_runner.WORKERS_ENV, "1")
    assert lane.land(gates, dry_run=True).ok is True  # the old loop is not throttled
    monkeypatch.setenv(gate_runner.WORKERS_ENV, "2")
    monkeypatch.setenv(gate_slots.SLOTS_ENV, "0")
    assert lane.land(gates, dry_run=True).ok is True  # the limit is off
    assert not folder.exists()
