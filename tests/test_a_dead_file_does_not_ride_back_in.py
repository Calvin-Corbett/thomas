"""A three-way merge cannot tell a deletion from an absence -- but this gate
can. Coverage for scripts/forge/gates/merge_resurrection_gate.py.

Fixtures build a throwaway git repo plus a throwaway graveyard.json (via the
real graveyard.py API, never hand-written JSON, so these tests break the same
way production would if the record shape ever changed) and drive
``run_check`` directly -- the fast, reliable path used by the sibling
monolith_guard tests. One CLI-level test at the bottom exercises ``main()``
through argparse to pin the human-readable FAIL message's shape (the death
id, deleted_on, reason, and the approval command), since that message is
what a person actually reads when this gate blocks them.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts.forge import graveyard
from scripts.forge.gates.merge_resurrection_gate import run_check

GATE_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "forge" / "gates" / "merge_resurrection_gate.py"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _init_git_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-b", "dev")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")


def _write_and_stage(repo: Path, rel_path: str, content: str = "content\n") -> None:
    path = repo / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    _git(repo, "add", rel_path)


def test_dead_file_path_fails_when_staged_without_approval(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    death_id = graveyard.record_death(
        repo, "file", "old/retired_module.py", "deadbeef", reason="replaced by new/module.py", by="test-suite"
    )
    _write_and_stage(repo, "old/retired_module.py")

    result = run_check(repo)

    assert result["ok"] is False
    assert result["mode"] == "staged"
    assert len(result["violations"]) == 1
    assert result["violations"][0]["id"] == death_id
    assert result["violations"][0]["name"] == "old/retired_module.py"


def test_unrelated_staged_add_passes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    graveyard.record_death(repo, "file", "old/retired_module.py", "deadbeef", reason="dead", by="test-suite")
    _write_and_stage(repo, "brand_new_module.py")

    result = run_check(repo)

    assert result["ok"] is True
    assert result["violations"] == []
    assert result["dead_file_records_consulted"] == 1
    assert result["added_paths_checked"] == 1


def test_approved_resurrection_passes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    death_id = graveyard.record_death(
        repo, "file", "old/retired_module.py", "deadbeef", reason="replaced", by="test-suite"
    )
    graveyard.record_resurrection_approval(
        repo, death_id, reason="bringing it back for a documented reason", by="test-suite"
    )
    _write_and_stage(repo, "old/retired_module.py")

    result = run_check(repo)

    assert result["ok"] is True
    assert result["violations"] == []


def test_a_re_death_after_approval_is_dead_again(tmp_path: Path) -> None:
    """Contract 4 from graveyard.py: approve, then kill the SAME path again
    -- the newest kind="file" record wins, so the path reports as dead once
    more even though an older approval exists for it."""
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    first_death = graveyard.record_death(repo, "file", "cycle.py", "sha1", reason="first death", by="test-suite")
    graveyard.record_resurrection_approval(repo, first_death, reason="approved once", by="test-suite")
    second_death = graveyard.record_death(repo, "file", "cycle.py", "sha2", reason="second death", by="test-suite")
    _write_and_stage(repo, "cycle.py")

    result = run_check(repo)

    assert result["ok"] is False
    assert result["violations"][0]["id"] == second_death


def test_diff_range_mode_catches_a_dead_path_reintroduced_between_refs(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _write_and_stage(repo, "keep.py")
    _git(repo, "commit", "-m", "base commit")
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()

    graveyard.record_death(repo, "file", "old/retired_module.py", "deadbeef", reason="dead", by="test-suite")
    _write_and_stage(repo, "old/retired_module.py")
    _git(repo, "commit", "-m", "reintroduce a dead path")
    head_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()

    result = run_check(repo, base=base_sha, head=head_sha)

    assert result["ok"] is False
    assert result["mode"] == "diff-range"
    assert result["violations"][0]["name"] == "old/retired_module.py"


def test_empty_graveyard_passes_and_reports_the_count_consulted(tmp_path: Path) -> None:
    """Honesty contract: zero dead-file records is a legitimate PASS, but the
    count consulted must still be visible in the report -- never a silent
    pass that looks identical to a pass on a populated graveyard."""
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _write_and_stage(repo, "brand_new_module.py")

    result = run_check(repo)

    assert result["ok"] is True
    assert result["dead_file_records_consulted"] == 0


def test_a_rename_shaped_reintroduction_of_a_dead_path_still_fails(tmp_path: Path) -> None:
    """Regression: this repo's git has rename detection on by default. Without
    --no-renames, `git mv <live file> <dead path>` (identical blob, so an
    exact content match) collapses into a single R100 status line that
    --diff-filter=A does not match at all -- the resurrection would not just
    evade the check, it would be invisible to the diff this gate reads. Built
    with a real `git mv` of a real committed file onto the dead path, not a
    synthetic status line, so this proves the actual git rename-detection
    behavior is defeated, not just the parser."""
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _write_and_stage(repo, "shared_content.py", "identical content\n")
    _git(repo, "commit", "-m", "seed: a live file with the content the dead path will be reintroduced as")

    death_id = graveyard.record_death(
        repo, "file", "old/retired_module.py", "deadbeef", reason="replaced by new/module.py", by="test-suite"
    )
    (repo / "old").mkdir(parents=True, exist_ok=True)
    _git(repo, "mv", "shared_content.py", "old/retired_module.py")

    result = run_check(repo)

    assert result["ok"] is False
    assert len(result["violations"]) == 1
    assert result["violations"][0]["id"] == death_id
    assert result["violations"][0]["name"] == "old/retired_module.py"


def test_a_case_scrambled_reintroduction_of_a_dead_path_still_fails(tmp_path: Path) -> None:
    """Regression: core.ignorecase=true on this repo (the Windows/NTFS
    default). A dead path re-added under a different letter-case is a
    genuine, distinct-string git ADD -- an exact dict lookup misses it, even
    though on a case-insensitive filesystem it lands on the exact same file
    as the one that died. The FAIL output must name BOTH spellings so the
    case trick is explicit, not just the record's original name."""
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    death_id = graveyard.record_death(
        repo, "file", "old/retired_module.py", "deadbeef", reason="replaced by new/module.py", by="test-suite"
    )
    _write_and_stage(repo, "Old/Retired_Module.py")

    result = run_check(repo)

    assert result["ok"] is False
    assert len(result["violations"]) == 1
    violation = result["violations"][0]
    assert violation["id"] == death_id
    assert violation["case_variant"] is True
    assert violation["name"] == "old/retired_module.py"
    assert violation["matched_path"] == "Old/Retired_Module.py"

    proc = subprocess.run(
        [sys.executable, str(GATE_SCRIPT), "--repo-root", str(repo)],
        capture_output=True,
        text=True,
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode != 0
    assert "old/retired_module.py" in combined
    assert "Old/Retired_Module.py" in combined


def test_cli_names_the_death_record_and_approval_command_on_failure(tmp_path: Path) -> None:
    """Pins the human-readable message a person actually reads: the dead
    path, the death id, deleted_on, reason, and the exact approval command
    naming that id -- run through main()/argparse, not run_check() directly,
    so a regression in the CLI's rendering (not just its return value) is
    caught here."""
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    death_id = graveyard.record_death(
        repo, "file", "old/retired_module.py", "deadbeef", reason="replaced by new/module.py", by="test-suite"
    )
    _write_and_stage(repo, "old/retired_module.py")

    proc = subprocess.run(
        [sys.executable, str(GATE_SCRIPT), "--repo-root", str(repo)],
        capture_output=True,
        text=True,
    )

    combined = proc.stdout + proc.stderr
    assert proc.returncode != 0
    assert "old/retired_module.py" in combined
    assert death_id in combined
    assert "replaced by new/module.py" in combined
    assert f"approve-resurrection {death_id}" in combined
