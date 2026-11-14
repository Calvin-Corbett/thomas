"""Real Git fixtures for shared-card tests, without rebuilding a green per hand-in."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.green_support import _GIT_ID, git
from tests.shared_card_git import GitReads, settings_key
from thomas.server import green_checkout, green_handoff


@pytest.fixture(scope="session")
def shared_card_seed(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    root = tmp_path_factory.mktemp("shared-card-seed")
    cage = root / "cage"
    cage.mkdir()
    with pytest.MonkeyPatch.context() as environment:
        environment.setenv("THOMAS_CAGE_ROOT", str(cage))
        _temporary_cage(cage)
        _git_home(root, environment)
        _direct_git(environment)
        repo = root / "blue"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "dev")
        (repo / "thomas").mkdir()
        (repo / "thomas" / "fix_me.py").write_text("VALUE = 1\n", encoding="utf-8")
        (repo / "README.md").write_text("blue\n", encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "init")
        (repo / ".git" / "info").mkdir(exist_ok=True)
    _SUBMISSIONS.clear()
    try:
        yield repo
    finally:
        _SUBMISSIONS.clear()


@pytest.fixture(scope="session")
def shared_card_green(tmp_path_factory: pytest.TempPathFactory, shared_card_seed: Path) -> green_checkout.Green:
    root = tmp_path_factory.mktemp("shared-card-green")
    with pytest.MonkeyPatch.context() as environment:
        environment.setenv("THOMAS_CAGE_ROOT", str(root / "cage"))
        environment.setenv("THOMAS_GREEN_ROOT", str(root / "green"))
        _git_home(root, environment)
        _direct_git(environment)
        _temporary_cage(root / "cage")
        return green_checkout.create_green(shared_card_seed, "parity-seed")


def _direct_git(environment: pytest.MonkeyPatch) -> None:
    if os.name != "nt":
        return
    launcher = shutil.which("git")
    if launcher:
        launcher = Path(launcher)
        binary = launcher.parent.parent / "mingw64" / "bin" / "git.exe"
        if binary.is_file():
            environment.setenv("PATH", str(binary.parent) + os.pathsep + os.environ["PATH"])


def _git_home(root: Path, environment: pytest.MonkeyPatch) -> None:
    for name in tuple(os.environ):
        if name.upper().startswith("GIT_"):
            environment.delenv(name)
    home = root / "git-home"
    home.mkdir()
    config = home / ".gitconfig"
    config.write_text(
        "[core]\n\tautocrlf = false\n[user]\n\tname = test\n\temail = test@example.invalid\n", encoding="utf-8"
    )
    environment.setenv("HOME", str(home))
    environment.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    environment.setenv("GIT_CONFIG_GLOBAL", str(config))
    environment.setenv("GIT_CONFIG_NOSYSTEM", "1")
    template = root / "empty-git-template"
    template.mkdir()
    environment.setenv("GIT_TEMPLATE_DIR", str(template))


@pytest.fixture
def blue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shared_card_seed: Path) -> Path:
    monkeypatch.setenv("THOMAS_CAGE_ROOT", str(tmp_path / "cage"))
    _temporary_cage(tmp_path / "cage")
    _git_home(tmp_path, monkeypatch)
    _direct_git(monkeypatch)
    monkeypatch.setattr(subprocess, "run", GitReads(subprocess.run))
    # Copy refs, index, config and worktree: tests must not share mutable Git state.
    repo = tmp_path / "blue"
    shutil.copytree(shared_card_seed, repo)
    monkeypatch.setenv("THOMAS_GREEN_ROOT", str(tmp_path / "green"))
    monkeypatch.setenv("THOMAS_BLUE_ROOT", str(repo))
    return repo


def _head(repo: Path) -> str:
    """Read loose fixture refs without spawning Git; defer other layouts to Git."""
    try:
        head = (repo / ".git" / "HEAD").read_text(encoding="ascii").strip()
        if head.startswith("ref: "):
            ref = repo / ".git" / head.removeprefix("ref: ")
            if not ref.is_file():
                return git(repo, "rev-parse", "HEAD")
            head = ref.read_text(encoding="ascii").strip()
        if len(head) == 40 and all(c in "0123456789abcdef" for c in head):
            return head
    except (OSError, UnicodeError):
        pass
    return git(repo, "rev-parse", "HEAD")


def _submit(blue: Path, execution_id: str, files: dict[str, str | None], *, chat: str = "chat-1") -> Path:
    """Build or reuse a real Git patch without changing HEAD, the worktree or its index."""
    _temporary_cage(blue.parent / "cage")
    base = _head(blue)
    # Object IDs pin committed attributes; config and info files are not in the tree.
    settings = settings_key(blue, os.environ)
    exclude = blue / ".git/info/exclude"
    key = (base, settings, exclude.read_bytes() if exclude.is_file() else b"", tuple(sorted(files.items())))
    if settings is None or key not in _SUBMISSIONS:
        # A private index and checkout let Git handle modes, attributes and newlines.
        # Only immutable patch bytes and changed paths are shared, never derived trees.
        with tempfile.TemporaryDirectory(dir=blue.parent, prefix="card-patch-") as folder:
            work = Path(folder) / "work"
            work.mkdir()
            env = green_checkout._clean_env()
            # These point only at fixture-owned settings, not the operator's Git config.
            env["GIT_CONFIG_GLOBAL"] = os.environ["GIT_CONFIG_GLOBAL"]
            env["GIT_CONFIG_NOSYSTEM"] = "1"
            env["GIT_INDEX_FILE"] = str(Path(folder) / "index")
            green = green_checkout.Green(execution_id, work, blue / ".git", base, blue)

            def run(*args: str) -> bytes:
                return subprocess.run(
                    green_checkout._git_command(green, *args),
                    cwd=work,
                    env=env,
                    capture_output=True,
                    check=True,
                ).stdout

            run("read-tree", "--reset", "-u", base)
            for rel, text in files.items():
                target = work / rel
                if text is None:
                    target.unlink()
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(text, encoding="utf-8")
            run("add", "--all")
            output = run(
                "diff",
                "--cached",
                "--raw",
                "-z",
                "--patch",
                "--binary",
                "--full-index",
                "--no-ext-diff",
                "--no-renames",
                base,
            )
            raw, separator, patch_bytes = output.partition(b"\0\0")
            changed = tuple(path.decode("utf-8", errors="surrogateescape") for path in raw.split(b"\0")[1::2])
            if not separator:
                raise AssertionError("fixture submission must change at least one file")
            patch = patch_bytes.decode("utf-8", errors="surrogateescape")
            if settings is not None:
                _SUBMISSIONS[key] = (patch, changed)
    else:
        patch, changed = _SUBMISSIONS[key]
    return _write_submission(blue, execution_id, base, patch, changed, chat)


_SUBMISSIONS: dict[tuple, tuple[str, tuple[str, ...]]] = {}


def _temporary_cage(expected: Path) -> None:
    cage = os.environ.get("THOMAS_CAGE_ROOT")
    expected = expected.resolve()
    temporary = Path(tempfile.gettempdir()).resolve()
    assert cage and Path(cage).resolve() == expected and expected != temporary and expected.is_relative_to(temporary), (
        "shared-card submissions require their own temporary THOMAS_CAGE_ROOT"
    )


def _write_submission(blue: Path, execution_id: str, base: str, patch: str, files: tuple[str, ...], chat: str) -> Path:
    _temporary_cage(blue.parent / "cage")
    green = green_checkout.Green(execution_id, blue, blue / ".git", base, blue)
    return green_handoff._write_submission(
        green, patch, sorted(files), "Make the change I asked for.", chat, f"self-{execution_id}"
    )
