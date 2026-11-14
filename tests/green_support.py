"""A small committed git repo to stand in for the running Thomas ("blue").

Shared by the green tests: tests/test_self_development_works_in_green.py
(the clone itself) and tests/test_a_finished_self_fix_waits_for_your_approval.py
(what happens when a run ends).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_GIT_ID = ("-c", "user.email=test@example.invalid", "-c", "user.name=test", "-c", "core.autocrlf=false")


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *_GIT_ID, *args], cwd=repo, capture_output=True, text=True, check=True)
    return proc.stdout.strip()


def make_blue(root: Path) -> Path:
    repo = root / "blue"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "thomas").mkdir()
    (repo / "thomas" / "fix_me.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "README.md").write_text("blue\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "init")
    return repo
