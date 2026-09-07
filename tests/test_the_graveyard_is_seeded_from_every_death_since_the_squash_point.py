"""The graveyard starts empty, but history does not: every path this dev
branch deleted since the public-main squash point, and every branch name
already archived, died before the registry existed to record it. The seed
tool backfills those records once and is safe to run again -- a second run
must add nothing.

Fixture repo layout (first-parent history only matters -- the seed reads
``git log --first-parent``):
  base (this is `merge_base`)
   -> deletes dead/gone.py, still absent from HEAD           -> FILE death
   -> deletes then re-adds dead/came_back.py                 -> NOT a death
      (present in HEAD -- deleted-then-restored is not dead)
  archive refs:
    refs/archive/worktree/salvage-only      -> BRANCH death (worktree source)
    refs/archive/custodian-only             -> BRANCH death (custodian source)
    refs/archive/worktree/both AND
    refs/archive/both                       -> ONE branch death (dedup;
                                                worktree source wins, reason
                                                notes the collision)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.forge import (
    graveyard,  # noqa: E402
    graveyard_seed,  # noqa: E402
)


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True)
    return proc.stdout


def _commit(cwd: Path, message: str) -> str:
    _git(cwd, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", message)
    return _git(cwd, "rev-parse", "HEAD").strip()


def _make_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(tmp_path, "init", "-b", "dev", "repo")

    (repo / "dead").mkdir()
    (repo / "dead" / "gone.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "dead" / "came_back.py").write_text("y = 1\n", encoding="utf-8")
    (repo / "alive.py").write_text("z = 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    merge_base = _commit(repo, "base")

    (repo / "dead" / "gone.py").unlink()
    (repo / "dead" / "came_back.py").unlink()
    _git(repo, "add", "-A")
    _commit(repo, "delete two files")

    (repo / "dead" / "came_back.py").write_text("y = 2\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _commit(repo, "restore came_back.py")

    head = _git(repo, "rev-parse", "HEAD").strip()
    _git(repo, "update-ref", "refs/archive/worktree/salvage-only", head)
    _git(repo, "update-ref", "refs/archive/custodian-only", head)
    _git(repo, "update-ref", "refs/archive/worktree/both", head)
    _git(repo, "update-ref", "refs/archive/both", head)

    return repo, merge_base


def test_seed_records_a_true_deletion_but_not_a_deletion_that_was_reverted(tmp_path: Path) -> None:
    repo, merge_base = _make_repo(tmp_path)

    counts = graveyard_seed.seed(repo, merge_base=merge_base)

    gy = graveyard.load(repo)
    dead_paths = gy.dead_file_paths()
    assert "dead/gone.py" in dead_paths
    assert dead_paths["dead/gone.py"]["reason"] == graveyard_seed._FILE_REASON
    assert dead_paths["dead/gone.py"]["by"] == "graveyard-seed"
    assert "dead/came_back.py" not in dead_paths, "restored file must not be recorded dead"
    assert "alive.py" not in dead_paths
    assert counts["files_added"] == 1


def test_seed_records_branch_deaths_from_both_archive_namespaces_and_dedupes_collisions(tmp_path: Path) -> None:
    repo, merge_base = _make_repo(tmp_path)

    counts = graveyard_seed.seed(repo, merge_base=merge_base)

    gy = graveyard.load(repo)
    dead_branches = gy.dead_ref_names()
    assert dead_branches == {"salvage-only", "custodian-only", "both"}
    assert counts["branches_added"] == 3

    branch_records = [r for r in gy.records if r["kind"] == "branch"]
    both_record = next(r for r in branch_records if r["name"] == "both")
    assert both_record["reason"] == graveyard_seed._BRANCH_REASON_WORKTREE + graveyard_seed._COLLISION_NOTE
    salvage_record = next(r for r in branch_records if r["name"] == "salvage-only")
    assert salvage_record["reason"] == graveyard_seed._BRANCH_REASON_WORKTREE
    custodian_record = next(r for r in branch_records if r["name"] == "custodian-only")
    assert custodian_record["reason"] == graveyard_seed._BRANCH_REASON_CUSTODIAN


def test_a_second_seed_run_adds_zero_records(tmp_path: Path) -> None:
    repo, merge_base = _make_repo(tmp_path)

    first = graveyard_seed.seed(repo, merge_base=merge_base)
    assert first["files_added"] + first["branches_added"] > 0

    record_count_after_first = len(graveyard.load(repo).records)

    second = graveyard_seed.seed(repo, merge_base=merge_base)

    assert second["files_added"] == 0
    assert second["branches_added"] == 0
    assert second["files_skipped"] > 0
    assert second["branches_skipped"] > 0
    assert len(graveyard.load(repo).records) == record_count_after_first


def test_seeding_does_not_re_record_a_path_already_dead_from_another_source(tmp_path: Path) -> None:
    repo, merge_base = _make_repo(tmp_path)
    graveyard.record_death(repo, "file", "dead/gone.py", "handrecorded", "recorded by hand first", "someone-else")

    counts = graveyard_seed.seed(repo, merge_base=merge_base)

    assert counts["files_skipped"] == 1
    assert counts["files_added"] == 0
    gy = graveyard.load(repo)
    assert gy.dead_file_paths()["dead/gone.py"]["by"] == "someone-else"


def test_the_cli_prints_the_counts(tmp_path: Path, capsys) -> None:
    repo, merge_base = _make_repo(tmp_path)

    rc = graveyard_seed.main(["--repo-root", str(repo), "--merge-base", merge_base])

    assert rc == 0
    out = capsys.readouterr().out
    assert "files added=1" in out
    assert "branches added=3" in out
