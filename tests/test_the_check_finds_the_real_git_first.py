"""The check before your card starts the real git rather than Git for Windows' launcher.

``git`` on this PC's PATH is ``C:\\Program Files\\Git\\cmd\\git.exe``, a launcher that starts
``..\\mingw64\\bin\\git.exe`` as a second process and waits for it. Every git a test starts was two processes.
A test now finds the real git first, the same binary from the same install, and a hook it runs still sees what
the launcher gave it. Anywhere without that layout, nothing changes.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from thomas.core import git_launcher
from thomas.server.proof import environment


def _layout(root: Path, *, real: bool = True, shell: bool = True) -> tuple[Path, Path]:
    """A fake Git for Windows under *root*: its launcher folder and the folder of the git it starts."""
    launcher, real_dir, unix = root / "Git" / "cmd", root / "Git" / "mingw64" / "bin", root / "Git" / "usr" / "bin"
    for folder in (launcher, real_dir, unix):
        folder.mkdir(parents=True, exist_ok=True)
    (launcher / "git.exe").write_bytes(b"launcher")
    if real:
        (real_dir / "git.exe").write_bytes(b"git")
    if shell:
        (unix / "sh.exe").write_bytes(b"sh")
    return launcher, real_dir


def _path(*folders: Path | str) -> str:
    return os.pathsep.join(str(folder) for folder in folders)


@pytest.fixture
def on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(git_launcher, "WINDOWS", True)


def test_the_real_git_goes_just_before_the_launcher(tmp_path: Path, on_windows: None) -> None:
    launcher, real = _layout(tmp_path)
    before, after = tmp_path / "system", tmp_path / "later"
    given = {"PATH": _path(before, launcher, after), "HOME": "kept"}

    env = git_launcher.real_git_first(given)

    assert env["PATH"] == _path(before, real, launcher, after), "every folder ahead of the launcher stays ahead"
    assert env["HOME"] == "kept"
    assert given["PATH"] == _path(before, launcher, after), "the caller's mapping is never changed"


def test_a_path_named_in_another_case_is_found(tmp_path: Path, on_windows: None) -> None:
    launcher, real = _layout(tmp_path)

    env = git_launcher.real_git_first({"Path": _path(launcher)})

    assert env == {"Path": _path(real, launcher)}


@pytest.mark.parametrize(
    "case",
    [
        "no git at all",
        "no real git behind the launcher",
        "no sh for its hooks",
        "a git that is not a launcher comes first",
        "the real git already comes first",
    ],
)
def test_path_is_left_alone_without_the_launcher_in_front(tmp_path: Path, on_windows: None, case: str) -> None:
    other = tmp_path / "other"
    other.mkdir()
    if case == "no git at all":
        folders: list[Path] = [other]
    elif case == "no real git behind the launcher":
        folders = [_layout(tmp_path, real=False)[0]]
    elif case == "no sh for its hooks":
        folders = [_layout(tmp_path, shell=False)[0]]
    elif case == "a git that is not a launcher comes first":
        (other / "git.exe").write_bytes(b"some other git")
        folders = [other, _layout(tmp_path)[0]]
    else:
        launcher, real = _layout(tmp_path)
        folders = [real, launcher]
    given = {"PATH": _path(*folders)}

    assert git_launcher.real_git_first(given) == given


def test_path_is_left_alone_off_windows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(git_launcher, "WINDOWS", False)
    given = {"PATH": _path(_layout(tmp_path)[0])}

    assert git_launcher.real_git_first(given) == given


def test_path_is_left_alone_when_msystem_is_already_set(tmp_path: Path, on_windows: None) -> None:
    """Started with MSYSTEM set, the real git adds nothing to its hooks' PATH, so it needs the launcher's help."""
    given = {"PATH": _path(_layout(tmp_path)[0]), "MSYSTEM": "MINGW64"}

    assert git_launcher.real_git_first(given) == given


def test_a_proofs_environment_finds_the_real_git_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, on_windows: None
) -> None:
    launcher, real = _layout(tmp_path)
    monkeypatch.delenv("MSYSTEM", raising=False)
    monkeypatch.setenv("PATH", _path(tmp_path / "system", launcher))

    env = environment.sandbox_env(tmp_path / "work", tmp_path / "data")
    chosen = environment.sandbox_env(tmp_path / "work", tmp_path / "data", {"PATH": "yours"})

    assert env["PATH"] == _path(tmp_path / "system", real, launcher)
    assert chosen["PATH"] == "yours", "a PATH the caller names is used as named"


@pytest.mark.parametrize("name", ["MSYSTEM", "msystem"])
def test_a_proof_given_msystem_keeps_the_launcher_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, on_windows: None, name: str
) -> None:
    """An MSYSTEM the caller names reaches the real git, which then adds nothing for its hooks: the launcher stays."""
    launcher, _real = _layout(tmp_path)
    monkeypatch.delenv("MSYSTEM", raising=False)
    monkeypatch.setenv("PATH", _path(tmp_path / "system", launcher))

    env = environment.sandbox_env(tmp_path / "work", tmp_path / "data", {name: "MINGW64"})

    assert env["PATH"] == _path(tmp_path / "system", launcher)


_GIT = Path(os.environ.get("PROGRAMFILES") or r"C:\Program Files") / "Git"
_REAL_LAYOUT = all(
    (_GIT / rel).is_file() for rel in ("cmd/git.exe", "mingw64/bin/git.exe", "usr/bin/sh.exe")
)  # what real_git_first itself requires
_HOOK = b'#!/bin/sh\n{ echo "PATH=$PATH"; echo "MSYSTEM=$MSYSTEM"; echo "SH=$(command -v sh)"; } > hook-saw.txt\n'


def _commit(git: str, repo: Path, hooks: Path, env: dict[str, str]) -> dict[str, str]:
    """Commit in *repo* with *git*; what its pre-commit hook saw."""
    settings = [
        f"core.hooksPath={hooks}",
        "user.name=check",
        "user.email=check@example.invalid",
        "commit.gpgsign=false",
    ]
    done = subprocess.run(
        [git, "-C", str(repo), *[part for pair in settings for part in ("-c", pair)], "commit", "-q", "--allow-empty",
         "-m", "hooked"],
        env=env, capture_output=True, text=True, timeout=120, check=False,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    saw = (repo / "hook-saw.txt").read_text(encoding="utf-8").splitlines()
    (repo / "hook-saw.txt").unlink()
    return dict(line.split("=", 1) for line in saw)


@pytest.mark.skipif(not (os.name == "nt" and _REAL_LAYOUT), reason="needs Git for Windows' launcher and its git")
def test_a_test_starts_the_same_git_and_its_hooks_see_what_the_launcher_gave_them(tmp_path: Path) -> None:
    windows = Path(os.environ.get("SYSTEMROOT") or r"C:\Windows")
    launcher = _GIT / "cmd"
    base = {k: v for k, v in os.environ.items() if not k.upper().startswith(("GIT_", "MSYSTEM"))}
    base["PATH"] = _path(windows / "System32", windows, launcher)
    env = git_launcher.real_git_first(base)
    found = shutil.which("git", path=env["PATH"])

    assert found is not None and Path(found).parent == _GIT / "mingw64" / "bin"
    same = [
        subprocess.run([git, "--version"], env=run_env, capture_output=True, text=True, check=True).stdout
        for git, run_env in ((str(launcher / "git.exe"), base), (found, env))
    ]
    assert same[0] == same[1], "the git that runs is the one the launcher starts"

    repo, hooks = tmp_path / "repo", tmp_path / "hooks"
    hooks.mkdir()
    (hooks / "pre-commit").write_bytes(_HOOK)
    subprocess.run([str(launcher / "git.exe"), "init", "-q", str(repo)], env=base, check=True, timeout=120)
    through_launcher = _commit(str(launcher / "git.exe"), repo, hooks, base)
    direct = _commit(found, repo, hooks, env)

    for saw in (through_launcher, direct):
        assert saw["MSYSTEM"] == "MINGW64" and saw["SH"] == "/usr/bin/sh"
        folders = saw["PATH"].split(":")
        assert {"/mingw64/bin", "/usr/bin"} <= set(folders), saw["PATH"]
        assert folders.index("/mingw64/bin") < folders.index("/usr/bin"), saw["PATH"]
    assert set(direct["PATH"].split(":")) == set(through_launcher["PATH"].split(":")), "the hook sees the same folders"
