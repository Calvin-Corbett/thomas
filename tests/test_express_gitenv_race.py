"""Referee core, round 5: races against the hold and the environment pins (each marker-writing repro, with a control)."""

from __future__ import annotations

import os
import shutil
import sys
import threading
from dataclasses import replace

import pytest
from scripts.cage.referee import gitenv

from tests.express_referee_support import lab  # noqa: F401
from tests.test_express_gitenv_families import Family
from tests.test_express_gitenv_hold import NoHold, config_of, evil_config_bytes


def racing_runner_calls(runner, fam, mutate, iterations: int, stop_on: str | None = None):
    """Run update-index repeatedly while ``mutate(stop)`` runs in a thread. Only the marker matters, never a count."""
    stop = threading.Event()
    thread = threading.Thread(target=mutate, args=(stop,))
    thread.start()
    try:
        for i in range(iterations):
            (fam.root / "probe.md").write_text(f"probe {i}\n")  # a changed file: git must run the clean filter again
            try:
                runner.run("update-index", "--add", "probe.md", check=False)
            except gitenv.GitUnsafe:
                pass
            if stop_on and stop_on in fam.ran():
                break
    finally:
        stop.set()
        thread.join()


@pytest.mark.skipif(sys.platform != "win32", reason="the hold is a Windows defence")
@pytest.mark.parametrize("how", ["delete_create", "hard_link"])
def test_a_config_deleted_and_recreated_or_hard_link_swapped_never_runs_the_marker(lab, how):
    """Major A: a missing file at hold time used to mean "no hold" without error; now it refuses."""
    fam = Family(lab, main=False)
    (lab.repo.root / ".gitattributes").write_text("* filter=evil\n")
    clean, evil = config_of(lab).read_bytes(), evil_config_bytes(lab, fam, "swap")
    source = lab.layout.root / "evil-source"
    source.write_bytes(evil)
    config = config_of(lab)

    def mutate(stop):
        while not stop.is_set():
            try:
                os.unlink(config)
                if how == "hard_link":
                    os.link(source, config)
                else:
                    config.write_bytes(evil)
            except OSError:
                pass
            stop.wait(0.001)
            for step in (lambda: os.unlink(config), lambda: config.write_bytes(clean)):
                try:
                    step()
                except OSError:
                    pass

    racing_runner_calls(fam.runner(), fam, mutate, 300)
    assert fam.ran() == set(), fam.ran()


def test_a_missing_or_locked_config_refuses_with_a_named_error(lab):
    fam = Family(lab, main=False)
    runner = fam.runner()
    saved = config_of(lab).read_bytes()
    if sys.platform == "win32":
        with open(config_of(lab), "r+b"):  # another handle with write access: sharing violation for the hold
            with pytest.raises(gitenv.GitUnsafe, match="could not hold"):
                runner.run("rev-parse", "--git-dir")
    config_of(lab).unlink()
    with pytest.raises(gitenv.GitUnsafe, match="could not hold"):
        runner.run("rev-parse", "--git-dir")
    config_of(lab).write_bytes(saved)
    (lab.repo.root / ".git" / "HEAD").unlink()
    with pytest.raises(gitenv.GitUnsafe, match="could not hold"):
        runner.run("rev-parse", "--git-dir")


@pytest.mark.skipif(sys.platform != "win32", reason="the hold is a Windows defence")
def test_a_required_file_never_yields_false_and_an_optional_one_may_be_absent(lab):
    from scripts.cage.referee.nofollow import UnsafeEntry, default_fs

    missing = lab.layout.root / "nothing-here"
    with default_fs().hold_file(missing) as optional:
        assert optional is False
    with pytest.raises(UnsafeEntry):
        with default_fs().hold_file(missing, True):
            pass
    with open(config_of(lab), "r+b"):
        with pytest.raises(UnsafeEntry):
            with default_fs().hold_file(config_of(lab), True):
                pass


def make_evil_common(lab, fam):
    common = lab.layout.root / "common"
    shutil.copytree(lab.repo.root / ".git", common)
    with open(common / "config", "a", encoding="utf-8") as out:
        out.write(f'[filter "e"]\n\tclean = {fam.cmd} common pass\n')
    (common / "info").mkdir(exist_ok=True)
    (common / "info" / "attributes").write_text("* filter=e\n")
    (lab.repo.root / ".gitattributes").write_text("")
    return common


def commondir_flipper(lab, common):
    pointer = lab.repo.root / ".git" / "commondir"

    def mutate(stop):
        while not stop.is_set():
            try:
                pointer.write_text(common.as_posix() + "\n")
                stop.wait(0.002)
                pointer.unlink()
            except OSError:
                pass

    return mutate


def test_a_commondir_created_during_the_calls_never_runs_the_other_repos_filter(lab):
    """Major B: GIT_COMMON_DIR is explicit, so git never consults a ``commondir`` file, however late it appears."""
    fam = Family(lab, main=False)
    common = make_evil_common(lab, fam)
    racing_runner_calls(fam.runner(), fam, commondir_flipper(lab, common), 300)
    assert fam.ran() == set(), fam.ran()


@pytest.mark.parametrize("pinned", [True, False])
def test_a_commondir_created_after_the_audit_runs_the_filter_only_without_git_common_dir(lab, monkeypatch, pinned):
    """The pointer appears between the audit and the command (the race, made exact). Pinned: ignored. Unpinned: it runs."""
    fam = Family(lab, main=False)
    common = make_evil_common(lab, fam)
    real_env, real_spawn = gitenv.GitRunner.env, gitenv.GitRunner._spawn

    def env_maybe_without_common(self, *args, **kwargs):
        env = real_env(self, *args, **kwargs)
        if not pinned:
            env.pop("GIT_COMMON_DIR", None)
        return env

    def pointer_then_spawn(self, args, *rest, **kwargs):
        if args[0] == "update-index":  # the caller's command, not one of the audit's own
            (lab.repo.root / ".git" / "commondir").write_text(common.as_posix() + "\n")
        return real_spawn(self, args, *rest, **kwargs)

    monkeypatch.setattr(gitenv.GitRunner, "env", env_maybe_without_common)
    monkeypatch.setattr(gitenv.GitRunner, "_spawn", pointer_then_spawn)
    runner = fam.runner()
    with pytest.raises(gitenv.GitUnsafe, match="changed while git ran"):  # noticed afterwards in both cases
        runner.run("update-index", "--add", "probe.md")
    assert ("common" in fam.ran()) is (not pinned), fam.ran()


def test_a_config_worktree_created_during_the_call_is_ignored_and_runs_nothing(lab, monkeypatch):
    fam = Family(lab, main=False)
    (lab.repo.root / ".gitattributes").write_text("* filter=wt\n")
    worktree_config = lab.repo.root / ".git" / "config.worktree"
    body = f'[filter "wt"]\n\tclean = {fam.cmd} wt pass\n'
    worktree_config.write_text(body)
    original = config_of(lab).read_bytes()
    config_of(lab).write_bytes(
        original + b"[core]\n\trepositoryformatversion = 1\n[extensions]\n\tworktreeConfig = true\n"
    )
    fam.plain()
    assert "wt" in fam.ran(), "with extensions.worktreeConfig git reads config.worktree: the vector is real"
    fam.reset()
    config_of(lab).write_bytes(original)  # the extension is off, which is all the audit accepts
    worktree_config.unlink()
    runner = fam.runner()
    real = gitenv.GitRunner._spawn

    def create_then_spawn(self, args, *rest, **kwargs):
        if args[0] == "update-index":  # the caller's command, not one of the audit's own
            worktree_config.write_text(body)  # after the audit, before git runs
        return real(self, args, *rest, **kwargs)

    monkeypatch.setattr(gitenv.GitRunner, "_spawn", create_then_spawn)
    with pytest.raises(gitenv.GitUnsafe, match="changed while git ran"):  # noticed afterwards, never run
        runner.run("update-index", "--add", "probe.md")
    assert fam.ran() == set()


def test_a_dot_git_file_in_the_working_folder_is_not_discovered_with_an_explicit_git_dir(lab):
    import subprocess

    fam = Family(lab, main=False)
    evil = lab.layout.root / "evil.git"
    shutil.copytree(lab.repo.root / ".git", evil)
    with open(evil / "config", "a", encoding="utf-8") as out:
        out.write(f'[filter "e"]\n\tclean = {fam.cmd} dotgit pass\n')
    work = lab.layout.root / "work2"
    work.mkdir()
    (work / ".git").write_text(f"gitdir: {evil.as_posix()}\n")
    (work / ".gitattributes").write_text("* filter=e\n")
    (work / "probe.md").write_text("probe\n")
    subprocess.run(
        [lab.repo.git_path, "update-index", "--add", "probe.md"], cwd=work, env=lab.repo.env(), capture_output=True
    )
    assert "dotgit" in fam.ran(), "git discovers the .git file when GIT_DIR is not set: the vector is real"
    fam.reset()
    runner = gitenv.direct(lab.repo.git_path, lab.repo.root / ".git", lab.layout.hooks, work)
    runner.run("update-index", "--add", "probe.md", check=False)
    assert fam.ran() == set()
