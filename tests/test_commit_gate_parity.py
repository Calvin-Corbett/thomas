"""The concurrent ladder says what the serial ladder said, on a corpus of staged states.

`reference_serial_ladder` below is the pre-change `_run_local_gates` copied verbatim (one `git ls-files` per gate, one gate
at a time, stop at the first refusal). Every state is judged by it first, then by the real landing path with one worker
with the default count (two) and with four. The verdict (pass, or which gate refused and with what output) and the blocker
class must be identical.

The gates (tests/commit_parity_gates.py) are real subprocesses with the real gates' NAMES, so the stage structure applies,
and small, checkable bodies: each reads the temporary index with `git diff --cached` as the real ones do. The states
(tests/commit_parity_states.py) cover a clean change, each gate violated in turn, a deletion, a rename, a big file, a
protected file, an unreviewed gate, and mixes whose first refusal lives in a different stage than a later one.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from scripts.crew.brief import gate_runner

from tests.commit_lane_support import git, mod
from tests.commit_parity_gates import GATE, ORDER, SCOPES, _registry, _seed
from tests.commit_parity_states import STATES


def _old_is_untracked(repo_root: Path, path: str) -> bool:
    if not path:
        return False
    proc = subprocess.run(
        ("git", "ls-files", "--", path),
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return proc.returncode == 0 and not proc.stdout.strip()


def reference_serial_ladder(repo_root, *, agent, index_path, selected, scope_selection, message, gates):
    """The pre-change `_run_local_gates`, verbatim apart from the helper names."""
    env = mod._temp_index_env(agent, index_path, scope_selection=scope_selection)
    env["THOMAS_COMMIT_MESSAGE"] = str(message or "")
    for gate_name, command in gates:
        if not mod._gate_applies(gate_name, selected):
            continue
        script = mod._gate_script(command)
        if _old_is_untracked(repo_root, script):
            continue
        resolved_command = mod._resolved_gate_command(gate_name, command, selected_paths=selected)
        proc = subprocess.run(resolved_command, cwd=repo_root, env=env, capture_output=True, text=True, check=False)
        output = ((proc.stdout or "") + (proc.stderr or "")).strip()
        if proc.returncode != 0:
            return False, gate_name, output
    return True, None, ""


def test_the_corpus_is_what_the_task_asked_for() -> None:
    assert len(STATES) >= 15
    assert (
        len(ORDER) >= 20
        and gate_runner.stage_of("workboard_claims") == 1
        and gate_runner.stage_of("monolith_guard") == 0
    )


@pytest.mark.parametrize("state", sorted(STATES))
def test_the_pooled_ladder_says_what_the_serial_ladder_said(state: str, tmp_path: Path, monkeypatch) -> None:
    for key in ("THOMAS_AGENT_SESSION_ID", "AGENT_SESSION_ID", "THOMAS_COMMIT_BASE"):
        monkeypatch.delenv(key, raising=False)
    gate_py = tmp_path / "gate.py"
    gate_py.write_text(GATE, encoding="utf-8")
    repo = _seed(tmp_path)
    board = repo / "plans" / "thomas" / "WORKBOARD.md"
    STATES[state](repo)
    gates = _registry(gate_py)

    # 1. the old ladder, on the same temporary index the landing will build
    scope = mod.ScopeSelection(scopes=tuple(SCOPES.split(",")), source=mod.CLAIM_SOURCE)
    selected = mod._selected_paths(repo, scope, ())
    index_path, holder = mod._prepare_temp_index(repo, agent="codex", selected_paths=selected, scope_selection=scope)
    try:
        ok, gate_name, output = reference_serial_ladder(
            repo,
            agent="codex",
            index_path=index_path,
            selected=selected,
            scope_selection=scope,
            message="m",
            gates=gates,
        )
    finally:
        holder.cleanup()

    # 2. the real landing path: serial (as a dry run, so the repo is left as it was), then four at a time (it lands)
    def landing(workers: int, **kwargs):
        monkeypatch.setenv(gate_runner.WORKERS_ENV, str(workers))
        return mod.commit_scoped_changes(
            message="feat: corpus",
            agent="codex",
            repo_root=repo,
            workboard_path=board,
            local_gate_commands=gates,
            **kwargs,
        )

    serial = landing(1, dry_run=True)
    default = landing(gate_runner.worker_count({}), dry_run=True)
    pooled = landing(4)
    head_after = git(repo, "rev-parse", "HEAD")

    if ok:
        assert serial.ok and default.ok and pooled.ok, (
            state,
            serial.message,
            default.message,
            pooled.message,
            pooled.gate_output,
        )
        assert pooled.commit_sha == head_after
        assert (serial.blocker_class, default.blocker_class, pooled.blocker_class) == (None, None, None)
        assert set(pooled.selected_paths) == set(selected)
    else:
        for result in (serial, default, pooled):
            assert (result.ok, result.blocker_class) == (False, "local_gate_failed"), (state, result.message)
            assert result.gate_name == gate_name, (state, result.gate_name, gate_name)
            assert result.gate_output == output, (state, result.gate_output, output)
        assert head_after == git(repo, "rev-parse", "master")  # nothing landed


def test_clean_states_really_land_and_refused_states_really_refuse(tmp_path: Path, monkeypatch) -> None:
    """Guards the corpus itself: a corpus whose every state passes (or every state fails) proves nothing."""
    monkeypatch.setenv(gate_runner.WORKERS_ENV, "4")
    gate_py = tmp_path / "gate.py"
    gate_py.write_text(GATE, encoding="utf-8")
    verdicts = {}
    for state in ("clean", "rename", "protected", "late_stage_refusal_before_early_stage_one"):
        root = tmp_path / state
        root.mkdir()
        repo = _seed(root)
        STATES[state](repo)
        result = mod.commit_scoped_changes(
            message="feat: corpus",
            agent="codex",
            repo_root=repo,
            workboard_path=repo / "plans" / "thomas" / "WORKBOARD.md",
            local_gate_commands=_registry(gate_py),
            dry_run=True,
        )
        verdicts[state] = (result.ok, result.gate_name)
    assert verdicts == {
        "clean": (True, None),
        "rename": (True, None),
        "protected": (False, "protected_files"),
        # registry order, not finishing order: workboard_claims (position 11) is reported although monolith_guard refuses first
        "late_stage_refusal_before_early_stage_one": (False, "workboard_claims"),
    }
