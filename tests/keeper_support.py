"""Fixtures for the keeper tests: a main repository with dev, a clone of it with work in progress, a temporary keep.

The fixtures run their own git (``fixture_git``) to build repositories; the keeper under test never does. The temporary
keep is an ordinary folder: these tests prove the keeper only ever creates files there, without needing the real
keep's access list.

A test module takes the ``world`` fixture with ``from tests.keeper_support import world``, as it takes ``_manifest``
(a capture's manifest from the keep) and ``_refused`` (a manifest's refused paths and their codes).
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest
from scripts.keeper.capture import Settings
from scripts.keeper.keep import load_manifest
from scripts.keeper.private import why_not_private

from tests.express_winfs import is_reparse_point


def git_binary() -> str:
    found = shutil.which("git")
    if not found:
        pytest.skip("git is not installed here")
    return str(Path(found).resolve())


def fixture_env(home: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        HOME=str(home),
        GIT_AUTHOR_NAME="Fixture",
        GIT_AUTHOR_EMAIL="fixture@example.invalid",
        GIT_COMMITTER_NAME="Fixture",
        GIT_COMMITTER_EMAIL="fixture@example.invalid",
    )
    return env


def fixture_git(cwd: Path, *args: str, check: bool = True, data: bytes | None = None) -> str:
    done = subprocess.run(
        [git_binary(), "-c", "init.defaultBranch=dev", "-c", "core.autocrlf=false", *args],
        cwd=cwd,
        env=fixture_env(cwd),
        **({"input": data} if data is not None else {"stdin": subprocess.DEVNULL}),
        capture_output=True,
        timeout=120,
    )
    if check and done.returncode:
        raise AssertionError(f"fixture git {args} failed: {done.stderr.decode('utf-8', 'replace')}")
    return done.stdout.decode("utf-8", "replace").strip()


def write(path: Path, data: bytes | str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode() if isinstance(data, str) else data)
    return path


@dataclass
class World:
    root: Path
    main: Path  # the main repository's working folder; its .git is the "main" the keeper reads dev from
    place: Path  # a clone of main with work in progress
    keep: Path
    work: Path
    dev: str
    place_commit: str
    secret: bytes

    @property
    def main_git(self) -> Path:
        return self.main / ".git"

    def settings(self, **extra) -> Settings:
        return Settings(keep=self.keep, work=self.work, git_path=git_binary(), **{"min_free_bytes": 0, **extra})


MAIN_FILES = {
    "a.txt": "alpha\n",
    "b/c.py": "print('c')\n",
    "gone.txt": "bye\n",
    "crlf.txt": "one\ntwo\n",
    ".gitignore": "*.log\nbuild/\n",
    "same-as-dev.txt": "x\n",
}


def build_world(tmp: Path) -> World:
    reason = why_not_private(tmp)
    if reason:  # the keeper refuses a keep or work folder others can read, so its tests need a private temp folder
        pytest.fail(f"{reason}. Run the keeper tests with --basetemp in an owner-only folder (C:\\r\\keeper-pytest)")
    main, place = tmp / "main", tmp / "place"
    main.mkdir(parents=True)
    fixture_git(main, "init", "-q")
    for rel, text in MAIN_FILES.items():
        write(main / rel, text)
    fixture_git(main, "add", "-A")
    fixture_git(main, "commit", "-q", "-m", "dev start")
    dev = fixture_git(main, "rev-parse", "HEAD")
    fixture_git(tmp, "clone", "-q", "--no-hardlinks", str(main), str(place))
    fixture_git(place, "checkout", "-q", "-b", "feature")
    write(place / "feature.txt", "only in the clone's commit\n")
    fixture_git(place, "add", "feature.txt")
    fixture_git(place, "commit", "-q", "-m", "feature commit the main repo has never seen")
    place_commit = fixture_git(place, "rev-parse", "HEAD")
    write(place / "a.txt", "alpha\nwork in progress that exists nowhere else\n")
    (place / "gone.txt").unlink()
    write(place / "new.txt", "untracked and only here\n")
    write(place / "debug.log", "ignored by *.log\n")
    write(place / "build" / "out.bin", b"\0ignored folder\0")
    write(place / "crlf.txt", b"one\r\ntwo\r\n")  # line-ending churn only
    secret = b"SECRET-" + os.urandom(8).hex().encode()
    write(tmp / "Documents" / "secret.txt", secret)
    keep, work = tmp / "keep", tmp / "work"
    keep.mkdir()
    work.mkdir()
    return World(tmp, main, place, keep, work, dev, place_commit, secret)


def _clear_and_retry(func, path, _exc) -> None:
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    func(path)


def remove_tree(path: Path) -> None:
    """Delete a fixture folder without ever walking through a junction (it is detached first)."""
    for dirpath, dirnames, _files in os.walk(path):
        for name in list(dirnames):
            if is_reparse_point(Path(dirpath, name)):
                os.rmdir(Path(dirpath, name))
                dirnames.remove(name)
    shutil.rmtree(path, onexc=_clear_and_retry)


def keep_files(keep: Path) -> list[Path]:
    return sorted(p for p in keep.rglob("*") if p.is_file())


@pytest.fixture
def world(tmp_path):
    w = build_world(tmp_path / "w")
    yield w
    remove_tree(tmp_path / "w")


def _manifest(world, result) -> dict:
    return load_manifest(world.keep, result["id"])[1]


def _refused(manifest: dict) -> dict[str, str]:
    return {r["path"]: r["code"] for r in manifest["refused"]}
