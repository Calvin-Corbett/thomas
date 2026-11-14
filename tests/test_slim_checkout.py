"""A slim checkout holds only the paths it is given, from git, and leaves no trace when removed.

Spec: docs/superpowers/specs/2026-10-29-kernel-plugins-fast-checks-design.md section 3 (Copy).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from thomas.server.proof import slim_checkout


def _repo(tmp_path: Path) -> tuple[Path, str]:
    blue = tmp_path / "blue"
    (blue / "a").mkdir(parents=True)
    for rel in ("a/one.py", "a/two.py", "b.txt", "c.txt"):
        (blue / rel).write_text(rel, encoding="utf-8")
    base = ["git", "-C", str(blue)]
    who = ["-c", "user.name=t", "-c", "user.email=t@t", "-c", "core.autocrlf=false"]
    subprocess.run([*base, "init", "-q"], check=True)
    subprocess.run([*base, *who, "add", "-A"], check=True)
    subprocess.run([*base, *who, "commit", "-q", "-m", "one"], check=True)
    tip = subprocess.run([*base, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    return blue, tip


def test_a_slim_copy_holds_only_its_paths_and_is_clean(tmp_path: Path) -> None:
    blue, tip = _repo(tmp_path)
    copy = slim_checkout.create_slim(blue, tmp_path / "slim", "c1", tip, ["a/one.py", "c.txt"])
    on_disk = sorted(p.relative_to(copy.work).as_posix() for p in copy.work.rglob("*") if p.is_file())
    assert on_disk == [".git", "a/one.py", "c.txt"] and copy.files == 2  # .git is the pointer to the git folder
    status = subprocess.run(["git", "-C", str(copy.work), "status", "--porcelain"], capture_output=True, text=True)
    assert status.stdout == ""
    tracked = subprocess.run(["git", "-C", str(copy.work), "ls-files"], capture_output=True, text=True).stdout.split()
    assert sorted(tracked) == ["a/one.py", "a/two.py", "b.txt", "c.txt"], "git still lists every path"
    slim_checkout.remove_slim(copy)
    assert not copy.work.exists() and not copy.git_dir.exists()


def test_a_name_already_in_use_is_refused(tmp_path: Path) -> None:
    blue, tip = _repo(tmp_path)
    copy = slim_checkout.create_slim(blue, tmp_path / "slim", "c1", tip, ["c.txt"])
    try:
        with pytest.raises(ValueError, match="already exists"):
            slim_checkout.create_slim(blue, tmp_path / "slim", "c1", tip, ["c.txt"])
    finally:
        slim_checkout.remove_slim(copy)
