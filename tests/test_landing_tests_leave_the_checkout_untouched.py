"""Landing tests keep their Git writes inside their temporary repositories."""

import os
import subprocess
import sys
from pathlib import Path

from tests.green_support import git, make_blue


def _checkout_files(repo: Path) -> set[str]:
    paths = git(repo, "ls-files", "--cached", "--others", "--exclude-standard", "-z").split("\0")
    return {name for name in paths if name and (repo / name).is_file()}


def test_landing_tests_leave_no_new_file_in_the_checkout(tmp_path: Path) -> None:
    checkout = Path(__file__).resolve().parents[1]
    team = make_blue(tmp_path)
    git(team, "checkout", "-qb", "dev")
    before = {path.relative_to(team): path.read_bytes() for path in team.rglob("*") if path.is_file()}
    original_files = _checkout_files(checkout)
    env = {name: value for name, value in os.environ.items() if not name.upper().startswith("GIT_")}
    env.update(GIT_DIR=str(team / ".git"), GIT_WORK_TREE=str(team), GIT_INDEX_FILE=str(team / ".git" / "index"))
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--basetemp",
            str(tmp_path / "landing-tests"),
            "tests/test_a_self_fix_lands_only_when_you_approve.py::test_approving_lands_exactly_the_change_on_dev_and_in_the_running_copy",
            "tests/test_every_green_is_saved_before_it_is_deleted.py::test_a_removed_green_leaves_a_capture_that_lands_what_it_held",
        ],
        cwd=checkout,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    after = {path.relative_to(team): path.read_bytes() for path in team.rglob("*") if path.is_file()}
    assert _checkout_files(checkout) == original_files, "landing tests left new files in the checkout"
    assert after == before, "landing tests wrote into the inherited team checkout"
    assert result.returncode == 0, result.stdout + result.stderr
