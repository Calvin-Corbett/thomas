"""Referee core, round 4: the reviewer's repros against ``direct()``, each with a control showing plain git runs the marker."""

from __future__ import annotations

import os
import shutil
import sys
import threading
from contextlib import contextmanager
from dataclasses import replace

import pytest
from scripts.cage.referee import gitenv
from scripts.cage.referee.configscan import scan

from tests.express_referee_support import lab  # noqa: F401
from tests.test_express_gitenv_families import Family


def config_of(lab):
    return lab.repo.root / ".git" / "config"


def add_filter(lab, fam, header: str, attribute: str, marker: str):
    with open(config_of(lab), "a", encoding="utf-8") as out:
        out.write(f"{header}\n\tclean = {fam.cmd} {marker} pass\n")
    (lab.repo.root / ".gitattributes").write_text(f"* filter={attribute}\n")


def test_a_subsection_holding_an_equals_sign_is_refused_because_dash_c_cannot_name_it(lab):
    """Blocker 1: ``-c filter.a=b.clean=`` splits at the first ``=``, so the override never matched the real key."""
    fam = Family(lab, main=False)
    add_filter(lab, fam, '[filter "a=b"]', "a=b", "eq")
    fam.plain()
    assert "eq" in fam.ran(), "plain git must run the filter, or this proves nothing"
    fam.reset()
    runner = fam.runner()
    assert any("filter.a=b.clean" in f and "cannot express" in f for f in gitenv.audit_repo_local(runner))
    with pytest.raises(gitenv.GitUnsafe, match="cannot express"):
        runner.run("update-index", "--add", "probe.md")
    assert fam.ran() == set()
    assert scan(["filter.a=b.clean"], "H")[1] and scan(["filter.a\nb.clean"], "H")[1]


@pytest.mark.parametrize(
    "sub,header",
    [
        ("a.b", '[filter "a.b"]'),
        ("a b", '[filter "a b"]'),
        ('l"fs', '[filter "l\\"fs"]'),
        ("a\\b", '[filter "a\\\\b"]'),
    ],
)
def test_dots_spaces_quotes_and_backslashes_in_a_subsection_get_a_matching_override(lab, sub, header):
    fam = Family(lab, main=False)
    add_filter(lab, fam, header, "unused", "variant")
    runner = fam.runner()
    assert gitenv.audit_repo_local(runner) == []
    assert runner.text("config", "--get", f"filter.{sub}.clean") == "", "the override must beat the repository's value"
    assert scan([f"filter.{sub}.clean"], "H")[0] == ["-c", f"filter.{sub}.clean="]


def make_common_copy(lab, fam):
    """The reviewer's repro: ``.git/commondir`` points at a copy of the repo whose config and attributes hold a filter."""
    common = lab.layout.root / "common"
    shutil.copytree(lab.repo.root / ".git", common)
    with open(common / "config", "a", encoding="utf-8") as out:
        out.write(f'[filter "e"]\n\tclean = {fam.cmd} common pass\n')
    (common / "info").mkdir(exist_ok=True)
    (common / "info" / "attributes").write_text("* filter=e\n")
    (lab.repo.root / ".git" / "commondir").write_text(common.as_posix() + "\n")
    (lab.repo.root / ".gitattributes").write_text("")


def test_a_commondir_pointer_is_refused_and_the_other_copys_filter_never_runs(lab):
    fam = Family(lab, main=False)
    make_common_copy(lab, fam)
    fam.plain()
    assert "common" in fam.ran(), "git must read the common dir's config, or this proves nothing"
    fam.reset()
    runner = fam.runner()
    findings = gitenv.audit_repo_local(runner)
    assert "commondir exists" in findings, findings  # git no longer reads it: see the race test below
    with pytest.raises(gitenv.GitUnsafe):
        runner.run("update-index", "--add", "probe.md")
    assert fam.ran() == set()


def test_a_gitdir_pointer_and_an_alternates_file_are_refused_by_name(lab):
    fam = Family(lab, main=False)
    runner = fam.runner()
    assert gitenv.audit_repo_local(runner) == []
    (lab.repo.root / ".git" / "gitdir").write_text("elsewhere\n")
    assert "gitdir exists" in gitenv.audit_repo_local(runner)
    (lab.repo.root / ".git" / "gitdir").unlink()
    (lab.repo.root / ".git" / "objects" / "info").mkdir(parents=True, exist_ok=True)
    (lab.repo.root / ".git" / "objects" / "info" / "alternates").write_text("elsewhere/objects\n")
    assert "objects/info/alternates exists" in gitenv.audit_repo_local(runner)
    with pytest.raises(gitenv.GitUnsafe, match="alternates"):
        runner.run("rev-parse", "--git-dir")


def evil_config_bytes(lab, fam, marker):
    return config_of(lab).read_bytes() + f'[filter "evil"]\n\tclean = {fam.cmd} {marker} pass\n'.encode()


class NoHold:
    """A file system that cannot hold anything (the portable fallback): only the after-the-fact check remains."""

    @contextmanager
    def hold_dir(self, path):
        yield

    @contextmanager
    def hold_file(self, path, required=False):
        yield False


def flip_config(lab, fam, runner, iterations: int):
    """The reviewer's repro: a thread atomically swaps ``.git/config`` between clean and filter-bearing while git runs."""
    clean = config_of(lab).read_bytes()
    evil = clean + f'[filter "evil"]\n\tclean = {fam.cmd} flip pass\n'.encode()
    (lab.repo.root / ".gitattributes").write_text("* filter=evil\n")
    stop, tally = threading.Event(), {"blocked": 0, "detected": 0}

    def flipper():
        tmp, state = config_of(lab).with_name("config.tmp"), 0
        while not stop.is_set():
            tmp.write_bytes((clean, evil)[state])
            state ^= 1
            try:
                os.replace(tmp, config_of(lab))
            except PermissionError:
                tally["blocked"] += 1

    thread = threading.Thread(target=flipper)
    thread.start()
    try:
        for i in range(iterations):
            (fam.root / "probe.md").write_text(f"probe {i}\n")  # a changed file: git must run the clean filter again
            try:
                runner.run("update-index", "--add", "probe.md", check=False)
            except gitenv.GitUnsafe:
                tally["detected"] += 1
            if "flip" in fam.ran():
                break
    finally:
        stop.set()
        thread.join()
    return tally


@pytest.mark.skipif(sys.platform != "win32", reason="only the Windows hold is a real defence")
def test_a_config_swapped_during_the_call_is_blocked_by_the_hold_and_the_marker_never_runs(lab):
    fam = Family(lab, main=False)
    flip_config(lab, fam, fam.runner(), iterations=25)
    assert fam.ran() == set(), "the flipping config got a filter to run"


@pytest.mark.skipif(sys.platform != "win32", reason="share modes are a Windows behaviour")
def test_a_held_config_cannot_be_replaced_or_written_until_it_is_released(lab):
    from scripts.cage.referee.nofollow import default_fs

    config, tmp = config_of(lab), config_of(lab).with_name("config.tmp")
    tmp.write_bytes(config.read_bytes())
    with default_fs().hold_file(config) as held:
        assert held is True
        with pytest.raises(PermissionError):
            os.replace(tmp, config)
        with pytest.raises(PermissionError):
            config.write_bytes(b"[user]\n")
        assert config.read_bytes()  # reading stays possible: git must be able to read it
    os.replace(tmp, config)  # released: now it can change
    with default_fs().hold_file(lab.layout.root / "no-such-file") as absent:
        assert absent is False


@pytest.mark.skipif(sys.platform != "win32", reason="only the Windows hold is a real defence")
@pytest.mark.parametrize("hold", [True, False])
def test_a_config_swapped_between_the_audit_and_the_command_runs_only_when_nothing_is_held(lab, monkeypatch, hold):
    """The race made exact: the swap happens right before the caller's command. Held: refused every time."""
    fam = Family(lab, main=False)
    (lab.repo.root / ".gitattributes").write_text("* filter=evil\n")
    evil = lab.layout.root / "evil-config"
    evil.write_bytes(evil_config_bytes(lab, fam, "flip"))
    runner = fam.runner() if hold else replace(fam.runner(), fs=NoHold())
    real_spawn, outcome = gitenv.GitRunner._spawn, []

    def swap_then_spawn(self, args, *rest, **kwargs):
        if args[0] == "update-index":
            try:
                os.replace(evil, config_of(lab))
                outcome.append("swapped")
            except PermissionError:
                outcome.append("blocked")
        return real_spawn(self, args, *rest, **kwargs)

    monkeypatch.setattr(gitenv.GitRunner, "_spawn", swap_then_spawn)
    try:
        runner.run("update-index", "--add", "probe.md")
    except gitenv.GitUnsafe:
        pass  # a swap is noticed afterwards
    assert outcome == (["blocked"] if hold else ["swapped"])
    assert ("flip" in fam.ran()) is (not hold), fam.ran()


def test_a_change_after_the_command_is_detected_and_the_result_discarded(lab, monkeypatch):
    """The portable fallback: it cannot undo a command that ran, but it never returns a result it cannot vouch for."""
    fam = Family(lab, main=False)
    runner = replace(fam.runner(), fs=NoHold())
    real = gitenv.GitRunner._spawn

    def spawn_then_change(self, *args, **kwargs):
        done = real(self, *args, **kwargs)
        config_of(lab).write_bytes(config_of(lab).read_bytes() + b"[user]\n\tname = changed\n")
        return done

    monkeypatch.setattr(gitenv.GitRunner, "_spawn", spawn_then_change)
    with pytest.raises(gitenv.GitUnsafe, match="changed while git ran"):
        runner.run("rev-parse", "--git-dir")


def test_a_gpg_ssh_default_key_command_does_not_run_under_commit_tree_dash_s(lab):
    """Minor 4: ``gpg.ssh.defaultKeyCommand`` is a command git runs when signing."""
    fam = Family(lab, main=False)
    with open(config_of(lab), "a", encoding="utf-8") as out:
        out.write(f'[gpg]\n\tformat = ssh\n[gpg "ssh"]\n\tdefaultKeyCommand = {fam.cmd} defaultkey fail\n')
    fam.plain()
    assert "defaultkey" in fam.ran(), "plain git must run the key command, or this proves nothing"
    fam.reset()
    runner = fam.runner()
    assert gitenv.audit_repo_local(runner) == []
    for args, data in fam.commands():
        runner.run(*args, data=data, check=False)
    assert fam.ran() == set()
    assert scan(["gpg.ssh.defaultkeycommand", "gpg.x.command"], "H")[0] == [
        "-c", "gpg.ssh.defaultkeycommand=", "-c", "gpg.x.command=",
    ]  # fmt: skip
