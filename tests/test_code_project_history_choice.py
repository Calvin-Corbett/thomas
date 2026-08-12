"""You must be able to open your own folders."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from thomas.forge.anvil import forge_code_projects as fcp


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=False, timeout=15)


def test_a_folder_without_history_asks_instead_of_refusing(tmp_path: Path) -> None:
    """The failure this fixes.

    117 of the owner's 121 projects had no .git and every one was unopenable.
    The refusal even promised that Thomas "asks first" for your own folders --
    nothing anywhere asked. It has to be answerable, so it is a distinct error
    carrying the folder it is about.
    """
    plain = tmp_path / "FreedomFlappy"
    plain.mkdir()

    with pytest.raises(fcp.ForgeCodeHistoryRequired) as caught:
        fcp.validate_project_root(plain, fallback=plain)

    assert caught.value.project_path == plain.resolve()


def test_choosing_to_work_without_undo_opens_the_folder(tmp_path: Path) -> None:
    plain = tmp_path / "FreedomTMS"
    plain.mkdir()

    resolved = fcp.validate_project_root(plain, fallback=plain, allow_without_history=True)

    assert resolved == plain.resolve()
    assert not (plain / ".git").exists(), "working without undo must not silently create a repo"


def test_choosing_to_set_up_history_makes_the_folder_revertible(tmp_path: Path) -> None:
    plain = tmp_path / "MyGame"
    plain.mkdir()
    (plain / "index.html").write_text("<h1>hi</h1>", encoding="utf-8")

    resolved = fcp.initialize_history(plain)

    assert (resolved / ".git").is_dir()
    # And the folder is now bindable by the ordinary path, with no special flag.
    assert fcp.validate_project_root(plain, fallback=plain) == resolved


def test_setting_up_history_is_idempotent(tmp_path: Path) -> None:
    plain = tmp_path / "Twice"
    plain.mkdir()

    first = fcp.initialize_history(plain)
    second = fcp.initialize_history(plain)

    assert first == second


def test_thomas_own_source_tree_is_refused_even_with_consent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No answer to the history question may unlock the product tree.

    A "make me a game" run editing Thomas's own checkout would let Revert sweep
    up unrelated work.
    """
    fake_source = tmp_path / "ThomasSource"
    inner = fake_source / "thomas" / "sub"
    inner.mkdir(parents=True)
    monkeypatch.setattr(fcp, "thomas_source_repo_root", lambda: fake_source.resolve())

    with pytest.raises(fcp.ForgeCodeProjectError, match="Thomas's own source tree"):
        fcp.initialize_history(inner)


def test_a_missing_folder_is_still_a_plain_failure_not_a_question(tmp_path: Path) -> None:
    """Only 'no history' is answerable. A folder that isn't there cannot be
    fixed by choosing something."""
    missing = tmp_path / "gone"

    with pytest.raises(fcp.ForgeCodeProjectError) as caught:
        fcp.validate_project_root(missing, fallback=missing, allow_without_history=True)

    assert not isinstance(caught.value, fcp.ForgeCodeHistoryRequired)


def test_history_required_is_catchable_as_the_ordinary_error(tmp_path: Path) -> None:
    """Callers that have not learned about the choice keep refusing, unchanged."""
    plain = tmp_path / "Legacy"
    plain.mkdir()

    with pytest.raises(fcp.ForgeCodeProjectError):
        fcp.validate_project_root(plain, fallback=plain)


def test_a_real_repository_is_unaffected(tmp_path: Path) -> None:
    repo = tmp_path / "HasGit"
    repo.mkdir()
    _git("init", "--initial-branch=main", cwd=repo)

    assert fcp.validate_project_root(repo, fallback=repo) == repo.resolve()


def test_git_runs_are_scoped_to_the_folder_the_user_picked(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    r"""Git refuses a repository whose directory belongs to another OS account
    -- "detected dubious ownership". The whole F:\DevHub tree on this machine
    carries a SID from a previous Windows install, so every project on that
    drive was unreadable: it could not be inspected, initialised, or opened.

    The trust is named for the exact folder, never a blanket safe.directory=*,
    and it is passed per invocation so no global git config is touched.
    """
    seen: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = list(cmd)
        seen["cwd"] = kwargs.get("cwd")

        class _P:
            returncode = 0
            stdout = str(tmp_path)
            stderr = ""

        return _P()

    monkeypatch.setattr(fcp.subprocess, "run", fake_run)
    fcp._git(["rev-parse", "--show-toplevel"], cwd=tmp_path)

    cmd = seen["cmd"]
    assert cmd[0] == "git"
    assert cmd[1] == "-c"
    assert cmd[2] == f"safe.directory={tmp_path}"
    assert "safe.directory=*" not in cmd
    assert seen["cwd"] == str(tmp_path)


def test_a_new_project_gets_its_own_folder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """"New project" used to send no project at all, so the server fell back to
    one shared scratch repo -- 26 entries deep, with the user's pacman,
    star-catcher and museum in it, and a single index.html each new build
    overwrote. It is also why Thomas was caught reading games made months
    earlier: they were in its working directory."""
    monkeypatch.setattr(fcp, "thomas_owned_root", lambda: tmp_path)

    first = fcp.create_named_project("Snake Game")
    second = fcp.create_named_project("Snake Game")

    assert first != second, "two projects with the same name must not share a folder"
    assert first.parent == second.parent == (tmp_path / "projects").resolve()
    assert (first / ".git").is_dir(), "a Thomas-owned project is initialised so edits can be undone"


def test_a_project_name_cannot_choose_where_the_project_lives(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(fcp, "thomas_owned_root", lambda: tmp_path)
    base = (tmp_path / "projects").resolve()

    for hostile in ("../../escape", r"..\..\escape", "C:/Windows/System32", "a/b/c", "..", "."):
        made = fcp.create_named_project(hostile)
        assert made.parent == base, f"{hostile!r} escaped to {made}"
