"""The faster card fixtures preserve hand-in bytes and isolate mutable repositories."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from scripts.cage import self_change_checks as checks

from tests import shared_card_support as support
from tests.green_support import git
from tests.shared_card_support import _SUBMISSIONS, _submit, blue, shared_card_green, shared_card_seed  # noqa: F401
from thomas.server import green_checkout, green_handoff
from thomas.tools import cage_shell


def _real_submit(blue: Path, files: dict[str, str | None], base: str, seed: green_checkout.Green) -> Path:
    support._temporary_cage(blue.parent / "cage")
    work, git_dir = green_checkout._paths("exec-real")
    work.parent.mkdir(parents=True, exist_ok=True)
    git_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(seed.work, work)
    shutil.copytree(seed.git_dir, git_dir)
    metadata = json.loads((git_dir / green_checkout.METADATA_NAME).read_text(encoding="utf-8"))
    metadata.update(execution_id="exec-real", blue=str(blue), base=base)
    (git_dir / green_checkout.METADATA_NAME).write_text(json.dumps(metadata), encoding="utf-8")
    green = green_checkout.Green("exec-real", work, git_dir, base, blue)
    green_checkout.git(green, "config", "core.worktree", str(work)).check_returncode()
    if seed.base != base:
        green_checkout.git(green, "fetch", str(blue), base).check_returncode()
        green_checkout.git(green, "reset", "--hard", base).check_returncode()
    assert green.base == base
    for rel, text in files.items():
        target = green.work / rel
        if text is None:
            target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
    # These private copies live under tmp_path; exercise settle without its redundant worktree deletion.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(green_checkout, "remove_green", lambda green: None)
        sub = green_handoff.settle("exec-real", promote=True, summary="Fixed it.", chat="chat-1")
    assert sub is not None
    return sub


@pytest.mark.parametrize(
    "files",
    [
        {"thomas/fix_me.py": "VALUE = 2\n", "thomas/new.py": "NEW = 1\n"},
        {"README.md": None, "thomas/new.py": "NEW = 1\n"},
        {"thomas/space name.py": "TEXT = 'caf\u00e9'", "empty.txt": ""},
        {"thomas/fix_me.py": "VALUE = 2\r\n"},
        {"thomas/fix_me.py": "VALUE = 1\n", "thomas/new.py": "NEW = 1\n"},
        {"thomas/fix_me.py": "VALUE = 2\n"},
        {"thomas/fix_me.py": "A = 1\nB = 2\n", "new.py": "FIRST = 1\nSECOND = 2\n"},
        {"thomas/fix_me.py": "A = 1\nB = 2\n"},
        {"thomas/tab\tname.py": "NEW = 1\n"},
    ],
    ids=[
        "edit-and-add",
        "delete-and-add",
        "text-and-paths",
        "crlf",
        "unchanged-path",
        "executable",
        "committed-crlf",
        "dirty-crlf",
        "quoted-path",
    ],
)
def test_fixture_hand_in_matches_a_real_green(
    blue: Path,
    shared_card_green: green_checkout.Green,
    files: dict[str, str | None],
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = request.node.callspec.id
    if case == "quoted-path" and os.name == "nt":
        pytest.skip("Windows filenames cannot contain tabs")
    if case == "executable":
        git(blue, "update-index", "--chmod=+x", "thomas/fix_me.py")
        git(blue, "commit", "-qm", "executable baseline")
    if case in {"committed-crlf", "dirty-crlf"}:
        (blue / "thomas/fix_me.py").write_bytes(b"VALUE = 10\r\n")
        if case == "committed-crlf":
            git(blue, "add", "-A")
            git(blue, "commit", "-qm", "CRLF baseline")
    _SUBMISSIONS.clear()
    calls = []
    real_run = subprocess.run

    def run(args, *pos, **kw):
        calls.append(args)
        return real_run(args, *pos, **kw)

    with monkeypatch.context() as patch:
        patch.setattr(subprocess, "run", run)
        fast = _submit(blue, "exec-fast", files)
        fast_calls = len(calls)
        base = json.loads((fast / "submission.json").read_text(encoding="utf-8"))["base"]
        calls.clear()
        real = _real_submit(blue, files, base, shared_card_green)
    assert fast_calls == 3
    assert len(calls) > fast_calls, "fixture setup must use fewer Git calls than a real green handoff"
    assert real is not None
    assert (fast / "change.patch").read_bytes() == (real / "change.patch").read_bytes()
    actual = json.loads((fast / "submission.json").read_text(encoding="utf-8"))
    expected = json.loads((real / "submission.json").read_text(encoding="utf-8"))
    for name in ("kind", "base", "files", "chat", "patch_sha256"):
        assert actual[name] == expected[name]
    changed = sorted(rel for rel, text in files.items() if rel != "thomas/fix_me.py" or text != "VALUE = 1\n")
    assert expected["files"] == changed
    patch_bytes = (real / "change.patch").read_bytes()
    assert patch_bytes, "parity must compare real edits, not two empty patches"
    if files.get("thomas/fix_me.py", "").startswith("VALUE = 2"):
        assert b"VALUE = 2" in patch_bytes
    if "thomas/space name.py" in files:
        assert "café" in patch_bytes.decode("utf-8")
    if case == "executable":
        assert b"100755" in patch_bytes


def test_cached_patch_applies_in_an_independent_repository(
    blue: Path, shared_card_seed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _SUBMISSIONS.clear()
    files = {"README.md": None, "thomas/cache.py": "CACHE = 1\n"}
    before = git(blue, "rev-parse", "HEAD")
    other = blue.parent / "other"
    shutil.copytree(shared_card_seed, other)
    real_run = subprocess.run
    calls: list[list[str]] = []

    def run(args: list[str], **kwargs):
        calls.append(args)
        return real_run(args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(subprocess, "run", run)
        first = _submit(blue, "exec-first", files)
    assert len(calls) == 3, "one read-tree, add and combined raw/patch diff"
    assert git(blue, "for-each-ref", "--format=%(refname)") == "refs/heads/dev"
    calls.clear()
    with monkeypatch.context() as patch:
        patch.setattr(subprocess, "run", run)
        second = _submit(other, "exec-second", files)
    assert calls == [], "a cached patch and a loose HEAD need no Git process"
    assert (second / "change.patch").read_bytes() == (first / "change.patch").read_bytes()
    tree = checks.derive_tree(other, before, (second / "change.patch").read_bytes())
    assert git(other, "show", f"{tree}:thomas/cache.py").strip() == "CACHE = 1"
    assert checks.text_at(other, tree, "README.md") == ""
    assert git(other, "rev-parse", "HEAD") == before
    assert git(other, "status", "--porcelain") == ""
    assert git(other, "for-each-ref", "--format=%(refname)") == "refs/heads/dev"
    (other / "thomas" / "fix_me.py").write_text("dirty\n", encoding="utf-8")
    assert (blue / "thomas" / "fix_me.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert git(shared_card_seed, "status", "--porcelain") == ""
    assert not (shared_card_seed / "thomas" / "cache.py").exists()


def test_seed_sets_a_temporary_cage_before_repository_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    previous = str(tmp_path / "previous-cage")
    monkeypatch.setenv(cage_shell.CAGE_ROOT_ENV, previous)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "previous-gitconfig"))
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "wrong.git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(tmp_path / "wrong-worktree"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(tmp_path / "wrong-index"))
    previous_home = os.environ.get("HOME")
    previous_path = os.environ.get("PATH")
    real_git = support.git
    roots = []

    def checked_git(repo, *args):
        cage = Path(os.environ[cage_shell.CAGE_ROOT_ENV])
        assert os.environ.get("GIT_DIR") is None
        assert os.environ.get("GIT_WORK_TREE") is None
        assert os.environ.get("GIT_INDEX_FILE") is None
        assert cage != Path(previous)
        assert cage.is_relative_to(tmp_path)
        assert cage.is_dir()
        if cage not in roots:
            roots.append(cage)
        return real_git(repo, *args)

    class Folders:
        def mktemp(self, name):
            folder = tmp_path / name
            folder.mkdir()
            return folder

    monkeypatch.setattr(support, "git", checked_git)
    fixture = shared_card_seed.__wrapped__(Folders())
    try:
        repo = next(fixture)
        assert repo.is_dir()
        assert len(roots) == 1
        assert Path(os.environ[cage_shell.CAGE_ROOT_ENV]) == Path(previous)
        assert os.environ["GIT_CONFIG_GLOBAL"] == str(tmp_path / "previous-gitconfig")
        assert os.environ["GIT_DIR"] == str(tmp_path / "wrong.git")
        assert os.environ["GIT_WORK_TREE"] == str(tmp_path / "wrong-worktree")
        assert os.environ["GIT_INDEX_FILE"] == str(tmp_path / "wrong-index")
        assert os.environ.get("HOME") == previous_home
        assert os.environ.get("PATH") == previous_path
    finally:
        fixture.close()
    assert os.environ[cage_shell.CAGE_ROOT_ENV] == previous


def test_shared_green_sets_cage_before_creation(tmp_path_factory: pytest.TempPathFactory) -> None:
    previous = os.environ[cage_shell.CAGE_ROOT_ENV]
    seen = []
    sentinel = object()

    def create(repo: Path, execution_id: str):
        root = Path(os.environ[cage_shell.CAGE_ROOT_ENV])
        assert root.is_relative_to(tmp_path_factory.getbasetemp())
        assert root.name == "cage"
        assert Path(os.environ["THOMAS_GREEN_ROOT"]).parent == root.parent
        seen.append((repo, execution_id))
        return sentinel

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(green_checkout, "create_green", create)
        result = shared_card_green.__wrapped__(tmp_path_factory, Path("seed"))
    assert result is sentinel
    assert seen == [(Path("seed"), "parity-seed")]
    assert os.environ[cage_shell.CAGE_ROOT_ENV] == previous


def test_private_repository_sets_cage_before_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seed = tmp_path / "seed"
    seed.mkdir()
    roots = []
    copytree = shutil.copytree

    def checked_copy(source, target):
        cage = Path(os.environ[cage_shell.CAGE_ROOT_ENV])
        assert cage == tmp_path / "cage"
        roots.append(cage)
        return copytree(source, target)

    monkeypatch.setenv(cage_shell.CAGE_ROOT_ENV, str(tmp_path / "previous-cage"))
    monkeypatch.setattr(support.shutil, "copytree", checked_copy)
    repo = blue.__wrapped__(tmp_path, monkeypatch, seed)
    assert repo.is_dir()
    assert roots == [tmp_path / "cage"]


def test_submission_refuses_a_non_temporary_cage(blue: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(cage_shell.CAGE_ROOT_ENV, raising=False)
    with pytest.raises(AssertionError, match="temporary THOMAS_CAGE_ROOT"):
        _submit(blue, "exec-no-cage", {"new.py": "NEW = 1\n"})
    monkeypatch.setenv(cage_shell.CAGE_ROOT_ENV, str(Path(blue.anchor) / "not-a-test-cage"))
    with pytest.raises(AssertionError, match="temporary THOMAS_CAGE_ROOT"):
        _submit(blue, "exec-real-cage", {"new.py": "NEW = 1\n"})


def test_patch_cache_accounts_for_repository_attributes(blue: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _SUBMISSIONS.clear()
    files = {"thomas/configured.py": "VALUE = 1\n"}
    text = _submit(blue, "exec-text", files)
    attributes = blue / ".git" / "info" / "attributes"
    attributes.write_text("*.py -diff\n", encoding="utf-8")
    calls = []
    real_run = subprocess.run

    def run(args, *pos, **kw):
        calls.append(args)
        return real_run(args, *pos, **kw)

    with monkeypatch.context() as patch:
        patch.setattr(subprocess, "run", run)
        binary = _submit(blue, "exec-binary", files)
    assert len(calls) == 3, "a repository attribute change must rebuild the patch"
    assert b"+VALUE = 1" in (text / "change.patch").read_bytes()
    assert b"GIT binary patch" in (binary / "change.patch").read_bytes()


def test_submission_requires_an_explicit_temporary_cage(blue: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = git(blue, "rev-parse", "HEAD")
    monkeypatch.delenv("THOMAS_CAGE_ROOT")
    with pytest.raises(AssertionError, match="temporary THOMAS_CAGE_ROOT"):
        support._write_submission(blue, "exec-no-cage", base, "patch", ("README.md",), "chat")
