"""Batched git reads: the same answers, from one process instead of dozens.

scripts/crew/brief/git_reads.py and the two gates that read blobs one `git show` at a time (enforcement_integrity: 66,
workboard_task_plans: one per plan). Every test pins an answer AND a process count, because a batch that quietly falls
back to the per-path read gives the same answer and none of the speed.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.crew.brief import git_reads
from scripts.forge.gates import workboard_task_plans as plans_gate

ROOT = Path(__file__).resolve().parents[1]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "master")
    _git(repo, "config", "user.name", "T")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "core.autocrlf", "false")  # a blob keeps the bytes it was given
    (repo / "dir").mkdir()
    (repo / "a.txt").write_bytes(b"one\n")
    (repo / "dir" / "b c.txt").write_bytes(b"two\r\nlines\r\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    return repo


def _count_calls(monkeypatch, module, name: str) -> list:
    calls: list = []
    real = getattr(module, name)

    def spy(*args, **kwargs):
        calls.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(module, name, spy)
    return calls


def test_cat_file_batch_reads_blobs_missing_names_and_the_index_in_one_process(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    (repo / "a.txt").write_bytes(b"changed\n")
    _git(repo, "add", "a.txt")
    calls = _count_calls(monkeypatch, git_reads, "run_git")
    got = git_reads.cat_file_batch(repo, ["HEAD:a.txt", "HEAD:dir/b c.txt", "HEAD:nope.txt", ":a.txt", ":dir/b c.txt"])
    assert got == {
        "HEAD:a.txt": b"one\n",
        "HEAD:dir/b c.txt": b"two\r\nlines\r\n",  # bytes untouched: no newline translation
        "HEAD:nope.txt": None,
        ":a.txt": b"changed\n",
        ":dir/b c.txt": b"two\r\nlines\r\n",
    }
    assert len(calls) == 1


def test_cat_file_batch_answers_none_for_a_tree_and_refuses_a_name_it_cannot_frame(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert git_reads.cat_file_batch(repo, ["HEAD:dir"]) == {"HEAD:dir": None}
    with pytest.raises(git_reads.GitReadError):
        git_reads.cat_file_batch(repo, ["HEAD:a.txt\nHEAD:dir/b c.txt"])
    assert git_reads.cat_file_batch(repo, []) == {}


def test_tracked_among_is_one_call_and_returns_only_what_git_tracks(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    (repo / "untracked.py").write_text("x = 1\n")
    calls = _count_calls(monkeypatch, git_reads, "run_git")
    got = git_reads.tracked_among(repo, ["a.txt", "dir/b c.txt", "untracked.py", "missing.py", ""])
    assert got == {"a.txt", "dir/b c.txt"}
    assert len(calls) == 1
    assert git_reads.tracked_among(repo, []) == set()


def test_tracked_among_never_reports_a_path_outside_the_repo_as_unreviewed(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    (repo / "untracked.py").write_text("x = 1\n")
    elsewhere = str(tmp_path / "elsewhere" / "gate.py")  # the one-call-per-path check said "not untracked" for these
    inside_absolute = str(repo / "a.txt")
    calls = _count_calls(monkeypatch, git_reads, "run_git")
    got = git_reads.tracked_among(repo, [elsewhere, inside_absolute, "untracked.py"])
    assert got == {elsewhere, inside_absolute}
    assert len(calls) == 1
    assert git_reads.tracked_among(repo, [elsewhere]) == {elsewhere}
    assert len(calls) == 1  # nothing left to ask git


def test_tracked_among_says_none_when_git_cannot_answer(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert git_reads.tracked_among(plain, ["a.py"]) is None


def _load_integrity():
    spec = importlib.util.spec_from_file_location(
        "enforcement_integrity_under_test", ROOT / "scripts" / "forge" / "gates" / "enforcement_integrity.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_enforcement_integrity_hashes_every_staged_script_through_one_process(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    for index in range(40):
        (repo / f"gate{index}.py").write_bytes(b"print(1)\r\n" * (index + 1))
    _git(repo, "add", "-A")
    ei = _load_integrity()
    monkeypatch.setattr(ei, "ROOT", repo)
    paths = [f"gate{i}.py" for i in range(40)] + ["gone.py", "dir/b c.txt"]
    expected = {p: ei._staged_content_hash(p) for p in paths}  # the old, one-process-per-path read
    calls = _count_calls(monkeypatch, ei.subprocess, "run")
    assert ei._staged_hashes(paths) == expected
    assert len(calls) == 1, f"fell back to per-path reads: {len(calls)} processes"
    assert expected["gone.py"] is None and expected["gate3.py"] is not None


def test_enforcement_integrity_falls_back_instead_of_trusting_a_stream_it_cannot_parse(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _repo(tmp_path)
    ei = _load_integrity()
    monkeypatch.setattr(ei, "ROOT", repo)
    got = ei._staged_hashes(["a.txt", "bad\nname.py"])  # a newline cannot be framed: per-path reads answer instead
    assert got["a.txt"] == ei._staged_content_hash("a.txt")
    assert got["bad\nname.py"] is None


def _plan(task_id: str, *, owner: str, scope: str) -> str:
    return (
        f"# PLAN for {task_id}\n\n- Owner: {owner}\n- Status: in_progress\n- Updated At: 2026-09-05T00:00:00+00:00\n"
        f"- Scope: {scope}\n\n## Summary\n\nbody\n\n## Approach\n\n- keep\n"
    )


def _plans_repo(root: Path, *, tasks: int = 6) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=root, check=True)  # keep TASK-3's CRLF in its blob
    rows_claims, rows_active, rows_plans = [], [], []
    for n in range(1, tasks + 1):
        agent = "worker" if n == 1 else f"other{n}"
        scope = f"src/t{n}.py"
        rows_claims.append(f"- agent={agent}; name=A{n}; role=solo; parent=none; scope={scope}; task=TASK-{n}")
        rows_active.append(f"- task_id=TASK-{n}; agent={agent}; scope={scope}; summary=s; status=active")
        rows_plans.append(
            f"- task_id=TASK-{n}; plan=plans/tasks/TASK-{n}/PLAN.md; owner={agent}; status=in_progress; updated_at=now; summary=s"
        )
        # a canonical plan, except 2 (wrong owner), 3 (CRLF line endings) and 4 (not in the index at all)
        text = _plan(f"TASK-{n}", owner="WRONG" if n == 2 else agent, scope=scope)
        path = root / "plans" / "tasks" / f"TASK-{n}" / "PLAN.md"
        path.parent.mkdir(parents=True)
        path.write_bytes((text.replace("\n", "\r\n") if n == 3 else text).encode("utf-8"))
    (root / "WORKBOARD.md").write_text(
        "# Thomas Workboard\n\n## Agent Claims (Active)\n\n"
        + "\n".join(rows_claims)
        + "\n\n## Active Tasks\n\n"
        + "\n".join(rows_active)
        + "\n\n## Issues / Blockers\n\n- none\n\n## Up For Grabs\n\n- none\n\n## Task Plans\n\n"
        + "\n".join(rows_plans)
        + "\n\n## Task Problems\n\n- none\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    if tasks >= 4:
        subprocess.run(["git", "rm", "-q", "--cached", "plans/tasks/TASK-4/PLAN.md"], cwd=root, check=True)
    return root / "WORKBOARD.md"


def test_task_plans_reads_every_plan_in_one_process_and_judges_them_as_it_always_did(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(plans_gate, "ROOT", tmp_path)
    board = _plans_repo(tmp_path)

    shows = []
    real_git = plans_gate._git

    def watching(*args):
        shows.append(args[:2])
        return real_git(*args)

    monkeypatch.setattr(plans_gate, "_git", watching)
    batched = plans_gate.evaluate_scoped(board, staged=True, agent="worker")
    plan_reads = [a for a in shows if a[0] == "show" and a[1] != ":WORKBOARD.md"]
    assert plan_reads == [], f"plans were read one process each: {plan_reads}"

    monkeypatch.setattr(plans_gate, "_prefetch_staged", lambda paths: None)  # the old read: one `git show` per plan
    unbatched = plans_gate.evaluate_scoped(board, staged=True, agent="worker")
    assert batched == unbatched
    violations, warnings = batched
    assert violations == []
    assert any("TASK-2" in w and "PLAN owner differs" in w for w in warnings), warnings
    assert any("TASK-4" in w and "not tracked in selected index" in w for w in warnings), warnings


def test_task_plans_cache_does_not_outlive_one_evaluation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(plans_gate, "ROOT", tmp_path)
    board = _plans_repo(tmp_path, tasks=2)
    first = plans_gate.evaluate_scoped(board, staged=True, agent="")
    (tmp_path / "plans" / "tasks" / "TASK-2" / "PLAN.md").write_text(
        _plan("TASK-2", owner="other2", scope="src/t2.py"), encoding="utf-8"
    )
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    second = plans_gate.evaluate_scoped(board, staged=True, agent="")
    assert any("TASK-2" in v and "PLAN owner differs" in v for v in first[0])
    assert not any("TASK-2" in v and "PLAN owner differs" in v for v in second[0]), second


def test_enforcement_integrity_verify_reads_the_index_through_the_batch_and_still_catches_a_tampered_script(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    repo = _repo(tmp_path)
    ei = _load_integrity()
    scripts = [f"gates/g{i}.py" for i in range(25)] + [ei.SELF_PATH]
    for path in scripts:
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(f"# {path}\n", encoding="utf-8")
    listed = ", ".join(f'"{p}"' for p in scripts)
    (repo / "agent_safety.toml").write_text(f"[protected]\nenforcement_scripts = [{listed}]\n", encoding="utf-8")
    monkeypatch.setattr(ei, "ROOT", repo)
    monkeypatch.setattr(ei, "MANIFEST_PATH", repo / "manifest.json")
    assert ei.generate_manifest() == 0
    _git(repo, "add", "-A")
    capsys.readouterr()

    calls = _count_calls(monkeypatch, ei.subprocess, "run")
    assert ei.verify(["--check-staged"]) == 0
    assert len(calls) <= 3, (
        f"{len(calls)} processes for {len(scripts)} scripts"
    )  # the manifest, one batch, nothing per script

    (repo / "gates" / "g3.py").write_text("print('rewritten to always pass')\n", encoding="utf-8")
    _git(repo, "add", "gates/g3.py")
    capsys.readouterr()
    assert ei.verify(["--check-staged"]) == 1
    assert "gates/g3.py" in capsys.readouterr().out
