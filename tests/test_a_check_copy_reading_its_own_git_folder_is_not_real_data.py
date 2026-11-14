"""A check copy that reads its own git folder has not touched your real data.

The cage keeps a check copy's files in LOCALAPPDATA/Thomas/green/work/<name> and its git folder beside them, in
LOCALAPPDATA/Thomas/green/git/<name>; the copy's ``.git`` is a one-line file that says so. Since 2026-11-06 Thomas
reads the commit he runs from git's own files (``thomas/core/head_sha.py``) instead of starting git, so a test that
starts a server opens ``green/git/<name>/HEAD`` from Python. The tripwire excused the copy's files and not its git
folder: on 2026-11-10 one finished change was checked three times, 72, 29 and 23 minutes, and each time both sides
ended "pytest exit 1 contradicts its report (...\\green\\git\\precard-...-base\\HEAD was opened by this test run",
so the check blamed dev and the change never reached your card.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests import conftest as guard
from tests.real_data_child_audit import own_git_folder, part_of_checkout
from tests.test_no_test_touches_your_real_data import _fake_real_folder, _tripwire


def _copy(root: Path) -> tuple[Path, Path]:
    """A check copy laid out as the cage lays one out: its files, and its git folder kept beside them."""
    checkout, git = root / "green" / "work" / "copy", root / "green" / "git" / "copy"
    checkout.mkdir(parents=True)
    git.mkdir(parents=True)
    (git / "HEAD").write_text("ref: refs/heads/dev\n", encoding="utf-8")
    (checkout / ".git").write_text(f"gitdir: {git.as_posix()}\n", encoding="utf-8")
    return checkout, git


def test_a_copy_says_where_its_git_folder_is(tmp_path: Path) -> None:
    checkout, git = _copy(tmp_path.resolve())
    assert own_git_folder(checkout) == git


def test_a_checkout_that_holds_its_git_folder_names_none(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    assert own_git_folder(tmp_path) is None
    assert own_git_folder(tmp_path / "no-such-checkout") is None


def test_only_the_copy_and_its_own_git_folder_are_part_of_it(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    checkout, git = _copy(root)
    assert part_of_checkout(checkout / "thomas" / "x.py", checkout, git)
    assert part_of_checkout(git / "HEAD", checkout, git)
    assert part_of_checkout(git, checkout, git)
    assert not part_of_checkout(root / "green" / "git" / "another-copy" / "HEAD", checkout, git)
    assert not part_of_checkout(root / "settings.json", checkout, git)
    assert not part_of_checkout(git / "HEAD", checkout, None)


def test_the_test_process_may_read_its_own_git_folder_and_nothing_beside_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot, _, check = _tripwire()
    root = _fake_real_folder(tmp_path)["root"].resolve()
    checkout, git = _copy(root)
    other = root / "green" / "git" / "another-copy"
    other.mkdir()
    (other / "HEAD").write_text("ref: refs/heads/dev\n", encoding="utf-8")
    monkeypatch.setattr(guard, "REAL_DATA_DIRS", (root,))
    monkeypatch.setattr(guard, "ROOT", checkout)
    monkeypatch.setattr(guard, "_OWN_GIT_FOLDER", git)
    monkeypatch.setattr(guard, "_DIRECT_REAL_DATA_ACCESS", set())
    before = snapshot([root])

    (git / "HEAD").read_text(encoding="utf-8")
    assert not (git / "commondir").exists()
    with pytest.raises(OSError):
        (git / "commondir").read_text(encoding="utf-8")  # head_sha asks for it; a copy of this kind has none

    session = SimpleNamespace(exitstatus=pytest.ExitCode.OK)
    assert check(session, before, [root], in_a_green=True) == []
    assert session.exitstatus == pytest.ExitCode.OK

    (other / "HEAD").read_text(encoding="utf-8")  # another copy's git folder is not this one's
    found = check(session, before, [root], in_a_green=True)
    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED
    assert any(str(other / "HEAD") in line for line in found)


def test_a_python_child_may_read_its_checkouts_git_folder_and_nothing_beside_it(tmp_path: Path) -> None:
    root = tmp_path.resolve() / "Thomas"
    checkout, git = _copy(root)
    (root / "settings.json").write_text("{}", encoding="utf-8")
    log = tmp_path / "child-log.jsonl"
    audit = Path(__file__).with_name("real_data_child_audit.py")
    # The run hands every child its own log and folders (conftest ``_audit_popen``), so the child names this test's
    # log and its made-up data folder itself, then installs the audit on the copy as a child of that copy would.
    program = (
        "import importlib.util, os, sys\n"
        f"os.environ['THOMAS_TEST_REAL_DATA_AUDIT_LOG'] = {str(log)!r}\n"
        f"os.environ['THOMAS_TEST_REAL_DATA_AUDIT_ROOTS'] = {json.dumps([str(root)])!r}\n"
        f"spec = importlib.util.spec_from_file_location('child_audit', {str(audit)!r})\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "sys.modules[spec.name] = module\n"
        "spec.loader.exec_module(module)\n"
        f"module.install({str(checkout)!r})\n"
        f"open({str(git / 'HEAD')!r}, encoding='utf-8').close()\n"
        f"open({str(root / 'settings.json')!r}, encoding='utf-8').close()\n"
    )

    done = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True, timeout=60)

    assert done.returncode == 0, done.stderr
    seen = [json.loads(line)[0] for line in log.read_text(encoding="utf-8").splitlines()]
    assert seen == [str(root / "settings.json")]
