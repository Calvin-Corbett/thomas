"""Referee core, real-checkout config families (plan B1 round 3): neutralise what can run, allow the harmless.

A repository like the owner's holds a hooks path, remotes, users, branches, a gpg program and git-lfs filter drivers.
``direct`` must accept it, and no call through the runner may start any command the repository names. Every test
that claims "nothing ran" first shows the same repository under plain scrubbed git DOES run those commands.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from scripts.cage.referee import gitenv
from scripts.cage.referee.configscan import classify, scan

from tests.express_referee_support import lab  # noqa: F401

PY = Path(sys.executable).as_posix()
MARK = (
    "import sys, pathlib\n"
    "d = pathlib.Path(sys.argv[1]); d.mkdir(exist_ok=True)\n"
    "(d / sys.argv[2]).write_text('ran')\n"
    "if sys.argv[3] == 'pass': sys.stdout.buffer.write(sys.stdin.buffer.read())\n"
    "elif sys.argv[3] == 'fail': sys.exit(1)\n"
)


class Family:
    """A lab repository dressed like a real checkout, every command it names writing a marker file."""

    def __init__(self, lab, extra_config: str = "", attributes: str = "* filter=lfs diff=x\n", main: bool = True):
        self.lab, self.root = lab, lab.repo.root
        base = lab.layout.root
        self.markers = base / "markers"
        (base / "mark.py").write_text(MARK)
        self.cmd = f"{PY} {(base / 'mark.py').as_posix()} {self.markers.as_posix()}"
        assert len(self.cmd.split()) == 3, "the marker command is written unquoted: the lab path must not hold spaces"
        self.tip = lab.repo.head()
        self.tree = lab.repo.text("rev-parse", "HEAD^{tree}")
        self.blob = lab.repo.text("rev-parse", "HEAD:README.md")
        self.patch = lab.repo.patch_for({"new-file.md": lab.repo.entry(b"new\n")})
        git_dir = self.root / ".git"
        gpg = base / "gpgfake"
        gpg.write_text(f"#!/bin/sh\n{self.cmd} gpg fail\n")
        for hook in ("reference-transaction", "post-index-change"):
            (git_dir / "hooks").mkdir(exist_ok=True)
            (git_dir / "hooks" / hook).write_text(f"#!/bin/sh\n{self.cmd} {hook} pass\n")
        config = extra_config
        if main:
            config += (
                f"[core]\n\thookspath = {(git_dir / 'hooks').as_posix()}\n"
                '[remote "origin"]\n\turl = https://example.invalid/x.git\n\tfetch = +refs/heads/*:refs/remotes/origin/*\n'
                "[user]\n\tname = Family\n\temail = family@example.invalid\n\tsigningkey = ABC\n"
                '[branch "dev"]\n\tremote = origin\n\tmerge = refs/heads/dev\n'
                f"[gpg]\n\tprogram = {gpg.as_posix()}\n\tformat = openpgp\n"
                f"[lfs]\n\trepositoryformatversion = 0\n"
                f'[filter "lfs"]\n\tclean = {self.cmd} clean pass\n\tsmudge = {self.cmd} smudge pass\n'
                f"\tprocess = {self.cmd} process fail\n\trequired = true\n"
                f'[diff "x"]\n\ttextconv = {self.cmd} textconv pass\n'
            )
        with open(git_dir / "config", "a", encoding="utf-8") as out:
            out.write(config)
        (self.root / ".gitattributes").write_text(attributes)
        (self.root / "probe.md").write_text("probe\n")

    def ran(self) -> set[str]:
        return {p.name for p in self.markers.iterdir()} if self.markers.exists() else set()

    def reset(self) -> None:
        for p in self.markers.glob("*"):
            p.unlink()

    def commands(self) -> list[tuple[list[str], bytes | None]]:
        """Every kind of call the referee makes, as (arguments, stdin)."""
        t = self.tip
        return [
            (["update-index", "--add", "probe.md"], None),
            (["read-tree", t], None),
            (["write-tree"], None),
            (["diff-tree", "-r", "--raw", f"{t}^{{tree}}", self.tree], None),
            (["apply", "--cached", "--check", "-"], self.patch),
            (["cat-file", "--filters", "--path=probe.md", self.blob], None),
            (["cat-file", "--textconv", f"{t}:README.md"], None),
            (["commit-tree", self.tree, "-p", t, "-m", "m"], None),
            (["commit-tree", "-S", self.tree, "-p", t, "-m", "m"], None),
            (["update-ref", "refs/heads/family", t], None),
            (["merge-base", t, t], None),
        ]

    def plain(self) -> None:
        for args, data in self.commands():
            subprocess.run(
                [self.lab.repo.git_path, "-C", str(self.root), *args],
                input=data,
                capture_output=True,
                env=self.lab.repo.env(),
                timeout=60,
            )

    def runner(self) -> gitenv.GitRunner:
        return gitenv.direct(self.lab.repo.git_path, self.root / ".git", self.lab.layout.hooks, self.root)


def test_a_real_checkout_config_is_accepted_and_nothing_it_names_runs(lab):
    fam = Family(lab)
    runner = fam.runner()
    assert gitenv.audit_repo_local(runner) == []  # (a) direct() accepts the key families
    results = [runner.run(*args, data=data, check=False) for args, data in fam.commands()]
    assert fam.ran() == set(), fam.ran()  # (b) not one marker
    assert [r.returncode for r in results[:5]] == [0, 0, 0, 0, 0]  # the calls really ran, they were not refused
    assert results[7].returncode == 0 and results[9].returncode == 0 and results[10].returncode == 0
    assert (lab.repo.root / ".git" / "refs" / "heads" / "family").exists()


def test_the_same_repository_under_plain_git_runs_every_command_it_names(lab):
    """(c) Not vacuous: scrubbed environment alone does not stop any of them."""
    fam = Family(lab)
    fam.plain()
    assert {"process", "gpg", "reference-transaction", "post-index-change"} <= fam.ran(), fam.ran()


def test_every_hook_in_the_real_hooks_folder_stays_silent(lab):
    fam = Family(lab, main=False)
    (lab.repo.root / ".git" / "config").write_text(
        (lab.repo.root / ".git" / "config").read_text()
        + f"[core]\n\thookspath = {(lab.repo.root / '.git' / 'hooks').as_posix()}\n"
    )
    fam.plain()
    assert {"reference-transaction"} <= fam.ran()
    fam.reset()
    runner = fam.runner()
    runner.run("update-ref", "refs/heads/silent", fam.tip)
    runner.run("read-tree", fam.tip, index=lab.layout.root / "idx")
    assert fam.ran() == set()


@pytest.mark.parametrize(
    "header,attribute",
    [('[FILTER "LFS"]', "LFS"), ('[filter "l\\"fs"]', 'l"fs'), ('[Filter "a.b"]', "a.b"), ('[filter "A B"]', "A B")],
)
def test_casing_quoting_and_dotted_subsections_are_still_classified(lab, header, attribute):
    """(f) git lists the subsection exactly as written; the override must use the same spelling."""
    if " " in attribute:
        pytest.skip("a space cannot be written in an attributes value")
    probe = Family(lab, main=False, attributes=f"* filter={attribute}\n")
    cmd = probe.cmd
    with open(lab.repo.root / ".git" / "config", "a", encoding="utf-8") as out:
        out.write(f"{header}\n\tclean = {cmd} clean pass\n\tsmudge = {cmd} smudge pass\n")
    probe.plain()
    assert {"clean"} <= probe.ran(), "the variant must run under plain git, or this proves nothing"
    probe.reset()
    runner = probe.runner()
    assert gitenv.audit_repo_local(runner) == []
    for args, data in probe.commands()[:6]:
        runner.run(*args, data=data, check=False)
    assert probe.ran() == set()


def test_the_two_header_line_with_a_filter_is_neutralised_and_never_runs(lab):
    fam = Family(lab, main=False)
    with open(lab.repo.root / ".git" / "config", "a", encoding="utf-8") as out:
        out.write(f'[core] [filter "evil"]\n\tclean = {fam.cmd} evil pass\n')
    (lab.repo.root / ".gitattributes").write_text("* filter=evil\n")
    fam.plain()
    assert "evil" in fam.ran()
    fam.reset()
    runner = fam.runner()
    assert gitenv.audit_repo_local(runner) == []
    runner.run("update-index", "--add", "probe.md")
    assert fam.ran() == set()


@pytest.mark.parametrize(
    "name,verdict",
    [
        ("filter.lfs.clean", "override"),
        ("filter.LFS.required", "override"),
        ('filter.l"fs.process', "override"),
        ("filter.a.b.smudge", "override"),
        ("diff.x.textconv", "override"),
        ("diff.external", "override"),
        ("merge.m.driver", "override"),
        ("core.hookspath", "override"),
        ("core.fsmonitor", "override"),
        ("core.attributesfile", "override"),
        ("core.pager", "override"),
        ("core.sshcommand", "override"),
        ("credential.helper", "override"),
        ("credential.https://h.example/.helper", "override"),
        ("gpg.program", "override"),
        ("gpg.ssh.program", "override"),
        ("commit.gpgsign", "override"),
        ("tag.gpgsign", "override"),
        ("remote.origin.url", "allow"),
        ("branch.codex/x.merge", "allow"),
        ("user.signingkey", "allow"),
        ("lfs.repositoryformatversion", "allow"),
        ("gpg.format", "allow"),
        ("gpg.ssh.allowedsignersfile", "allow"),
        ("url.https://x/.insteadof", "allow"),
        ("alias.st", "allow"),
        ("core.longpaths", "allow"),
        ("include.path", "refuse"),
        ("includeif.gitdir:/.path", "refuse"),
        ("core.worktree", "refuse"),
        ("foo.bar", "refuse"),
        ("filter.lfs.other", "refuse"),
        ("core.hookspath.x", "refuse"),
    ],
)
def test_classify_each_key_family(name, verdict):
    assert classify(name, "H")[0] == verdict


def test_the_overrides_use_the_spelling_git_listed_and_the_given_hooks_folder():
    args, refused = scan(["filter.LFS.clean", "filter.LFS.required", "core.hookspath", "gpg.program"], "E:/empty")
    assert refused == []
    assert args == [
        "-c",
        "filter.LFS.clean=",
        "-c",
        "filter.LFS.required=false",
        "-c",
        "core.hookspath=E:/empty",
        "-c",
        "gpg.program=",
    ]


def test_a_textconv_driver_does_not_run_either(lab):
    fam = Family(lab, main=False, attributes="* diff=x\n")
    with open(lab.repo.root / ".git" / "config", "a", encoding="utf-8") as out:
        out.write(f'[diff "x"]\n\ttextconv = {fam.cmd} textconv pass\n')
    fam.plain()
    assert "textconv" in fam.ran(), "the textconv must run under plain git, or this proves nothing"
    fam.reset()
    runner = fam.runner()
    assert gitenv.audit_repo_local(runner) == []
    refused = runner.run("cat-file", "--textconv", f"{fam.tip}:README.md", check=False)
    assert refused.returncode != 0  # an emptied textconv command fails closed ("cannot spawn"); nothing ran
    runner.run("diff", "--no-index", "--textconv", "probe.md", "README.md", check=False)
    assert fam.ran() == set()


def test_the_checkout_is_given_to_git_as_safe_directory_on_the_command_line(lab, monkeypatch):
    fam = Family(lab)
    seen: list[list[str]] = []
    real = subprocess.run
    monkeypatch.setattr(
        gitenv.subprocess, "run", lambda command, **kw: (seen.append(list(command)), real(command, **kw))[1]
    )
    fam.runner().run("rev-parse", "--git-dir")
    main = [c for c in seen if c[-2:] == ["rev-parse", "--git-dir"]][0]  # the caller's call, not the audit's
    assert f"safe.directory={lab.repo.root.as_posix()}" in main
    assert f"core.hooksPath={lab.layout.hooks}" in main and "filter.lfs.required=false" in main
