"""Referee core, scrubbed git (plan B1; invariant 38): one door to git, a pinned binary, and nothing repo-local runs."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from scripts.cage.referee import gitenv
from scripts.cage.referee.charter import Charter
from scripts.cage.referee.derive import evaluate
from scripts.cage.referee.gitenv import GitFailed, GitUnsafe, audit_repo_local, direct

from tests.express_referee_support import FRAGMENT, decide, git, lab, patch_adding  # noqa: F401

HOSTILE = {  # variables a parent process could set to steer git
    "GIT_DIR": "elsewhere",
    "GIT_WORK_TREE": "elsewhere",
    "GIT_EXTERNAL_DIFF": "evil",
    "GIT_CONFIG_GLOBAL": "evil",
    "GIT_CONFIG_PARAMETERS": "'core.hookspath'='evil'",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES": "elsewhere",
    "GIT_INDEX_FILE": "elsewhere",
    "GIT_SSH_COMMAND": "evil",
    "GIT_PAGER": "evil",
}


def test_git_calls_use_scrubbed_env(lab, git, monkeypatch):
    """Invariant 38: every call is the pinned absolute binary with an explicit GIT_DIR and no inherited git variables."""
    seen: list[tuple[list[str], dict[str, str]]] = []
    real = subprocess.run

    def spy(command, **kwargs):
        seen.append((list(command), dict(kwargs["env"])))
        return real(command, **kwargs)

    tip, patch = (
        lab.repo.head(),
        patch_adding(lab, {"changelog.d/lab-env-note.md": FRAGMENT}),
    )  # the lab's own git, unspied
    for key, value in HOSTILE.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(gitenv.subprocess, "run", spy)
    assert evaluate(git, tip, patch, Charter()).lane == "express"
    assert len(seen) >= 6
    for command, env in seen:
        assert command[0] == lab.repo.git_path
        assert env["GIT_DIR"] == str(git.git_dir) and env["GIT_CONFIG_NOSYSTEM"] == "1"
        assert env["GIT_CONFIG_GLOBAL"] == gitenv.os.devnull
        assert not {
            "GIT_EXTERNAL_DIFF",
            "GIT_WORK_TREE",
            "GIT_CONFIG_PARAMETERS",
            "GIT_SSH_COMMAND",
            "GIT_PAGER",
        } & set(env)
        assert not any(k.startswith("GIT_") and k not in git.env(None) | {"GIT_INDEX_FILE": ""} for k in env)
        assert "core.hooksPath=" + str(git.hooks_dir) in command and "core.fsmonitor=false" in command
        assert f"core.attributesFile={gitenv.os.devnull}" in command


def test_a_relative_or_missing_git_path_is_refused(lab, git):
    for bad in ("git", "git.exe", str(lab.layout.root / "no-such-git.exe")):
        with pytest.raises(ValueError):
            gitenv.GitRunner(bad, git.git_dir, git.hooks_dir, git.cwd)


def test_a_failing_git_is_an_error_and_a_hung_git_is_a_crash(git):
    with pytest.raises(GitFailed) as failed:
        git.run("rev-parse", "--verify", "0" * 40 + "^{commit}")
    assert not failed.value.crashed
    quick = gitenv.GitRunner(git.git_path, git.git_dir, git.hooks_dir, git.cwd, timeout=0.000001)
    with pytest.raises(GitFailed) as hung:
        quick.run("--version")
    assert hung.value.crashed


MARKER = "filter-ran.txt"


def plant_filter(lab) -> tuple[object, str]:
    """A clean filter in the repository's own config and an info/attributes line that selects it for every file."""
    script = lab.layout.root / "evil_filter.py"
    marker = lab.layout.root / MARKER
    script.write_text(
        f"import sys\nopen({str(marker)!r}, 'w').write('ran')\nsys.stdout.buffer.write(sys.stdin.buffer.read())\n"
    )
    command = f'\\"{Path(sys.executable).as_posix()}\\" \\"{script.as_posix()}\\"'  # git config quotes need escaping
    git_dir = lab.repo.root / ".git"
    with open(git_dir / "config", "a", encoding="utf-8") as config:
        config.write(f'[filter "evil"]\n\tclean = {command}\n\tsmudge = {command}\n\trequired = false\n')
    (git_dir / "info").mkdir(exist_ok=True)
    (git_dir / "info" / "attributes").write_text("* filter=evil\n")
    return marker, command


def test_a_filter_planted_in_the_repo_config_does_not_run(lab, git):
    """Binding finding: repo-local config and info/attributes must not run a command, even with a scrubbed environment."""
    tip, patch = lab.repo.head(), patch_adding(lab, {"changelog.d/lab-filter-note.md": FRAGMENT})
    marker, _ = plant_filter(lab)  # from here on nothing may call the lab's git: it re-seals the config it is given
    # control: a plain scrubbed-environment git (no referee wrapper) does run the planted filter, so the plant is real
    plain = [lab.repo.git_path, "-C", str(lab.repo.root), "hash-object", "--path=probe.md", "--stdin"]
    subprocess.run(plain, input=b"probe\n", capture_output=True, env=lab.repo.env(), check=True)
    assert marker.exists(), "the planted filter must be able to run, or this test proves nothing"
    marker.unlink()
    assert evaluate(git, tip, patch, Charter()).lane == "express"
    git.run("hash-object", "-w", "--path=probe.md", "--stdin", data=b"probe\n")
    blob_id = git.text("hash-object", "-w", "--stdin", data=b"x\n")
    git.run("cat-file", "--filters", "--path=probe.md", blob_id)
    git.run("cat-file", "--textconv", "--path=probe.md", blob_id, check=False)
    assert not marker.exists(), "the referee's git ran a command planted in the repository"


def audit(lab):
    runner = direct(lab.repo.git_path, lab.repo.root / ".git", lab.layout.hooks, lab.layout.root)
    return runner, audit_repo_local(runner)


def test_the_direct_runner_refuses_instead_of_running_a_planted_filter(lab):
    marker, _ = plant_filter(lab)
    runner, findings = audit(lab)
    assert findings == ["info/attributes is not empty"]  # the filter is neutralised; the attributes line is refused
    with pytest.raises(GitUnsafe):
        runner.run("hash-object", "-w", "--path=probe.md", "--stdin", data=b"probe\n")
    assert not marker.exists()


def test_a_config_line_with_two_section_headers_is_refused_and_nothing_runs(lab):
    """The reviewed bypass: ``[core] [filter "evil"]`` hid ``filter.evil.clean`` from a header-by-header scan."""
    script = lab.layout.root / "evil_two.py"
    marker = lab.layout.root / "two-header-ran.txt"
    script.write_text(
        f"import sys\nopen({str(marker)!r}, 'w').write('ran')\nsys.stdout.buffer.write(sys.stdin.buffer.read())\n"
    )
    command = f'\\"{Path(sys.executable).as_posix()}\\" \\"{script.as_posix()}\\"'
    with open(lab.repo.root / ".git" / "config", "a", encoding="utf-8") as config:
        config.write(f'[core] [filter "evil"]\n\tclean = {command}\n')
    (lab.repo.root / ".gitattributes").write_text("* filter=evil\n")
    (lab.repo.root / "probe.md").write_text("probe\n")
    plain = [lab.repo.git_path, "-C", str(lab.repo.root), "update-index", "--add", "probe.md"]
    subprocess.run(plain, capture_output=True, env=lab.repo.env(), check=True)
    assert marker.exists(), "the two-header filter must run under plain git, or this test proves nothing"
    marker.unlink()
    runner, findings = audit(lab)
    assert findings == []  # neutralised, not refused: ``-c filter.evil.clean=`` beats the repository's own value
    assert runner.git_dir.name == ".git"
    runner = gitenv.direct(runner.git_path, runner.git_dir, runner.hooks_dir, lab.repo.root)
    runner.run("update-index", "--add", "probe.md")
    assert not marker.exists()


@pytest.mark.parametrize(
    "line,named,why",
    [
        ("[include]\n\tpath = elsewhere\n", "include.path", "pulls in files"),
        ('[includeIf "gitdir:/"]\n\tpath = elsewhere\n', "includeif.gitdir:/.path", "pulls in files"),
        ("[CORE]\n\tWorkTree = elsewhere\n", "core.worktree", "moves the work tree"),
        ("[foo]\n\tbar = 1\n", "foo.bar", "unknown"),
        ("[core]\n\tunknownkey = 1\n", "core.unknownkey", "unknown"),
        ("[extensions]\n\tworktreeConfig = true\n", "extensions.worktreeconfig", "unknown"),
        ('[filter "f"]\n\tother = 1\n', "filter.f.other", "unknown"),
        ('[core] [diff "d"]\n\tweird = evil\n', "diff.d.weird", "unknown"),
    ],
)
def test_unknown_includes_and_a_moved_worktree_are_refused_by_name(lab, line, named, why):
    config = lab.repo.root / ".git" / "config"
    assert audit(lab)[1] == []  # a clean repository passes
    config.write_text(config.read_text() + line)
    runner, findings = audit(lab)
    assert any(named in f and why in f for f in findings), findings
    with pytest.raises(GitUnsafe, match="config key"):
        runner.run("rev-parse", "--git-dir")


def test_a_harmless_config_still_passes(lab):
    config = lab.repo.root / ".git" / "config"
    config.write_text(
        config.read_text() + "[core]\n\tautocrlf = true\n\teol = lf\n\tlongpaths = true\n\tsymlinks = false\n"
    )
    runner, findings = audit(lab)
    assert findings == []
    assert runner.text("rev-parse", "--is-bare-repository") in {"true", "false"}


def test_an_unreadable_config_or_a_worktree_config_is_refused(lab):
    (lab.repo.root / ".git" / "config").write_text("[core\n\tbroken\n")
    assert audit(lab)[1] != []
    (lab.repo.root / ".git" / "config").write_text(gitenv.PRISTINE_CONFIG.decode())
    (lab.repo.root / ".git" / "config.worktree").write_text("")
    assert "config.worktree exists" in audit(lab)[1]


def test_the_isolated_view_never_changes_the_real_repository(lab, git):
    real = lab.repo.root / ".git"
    before = (
        lab.repo.head(),
        (real / "config").read_bytes(),
        sorted(p.name for p in (real / "refs" / "heads").iterdir()),
    )
    for name in ("one", "two"):
        assert decide(lab, git, patch_adding(lab, {f"changelog.d/lab-{name}-note.md": FRAGMENT})).lane == "express"
    after = (
        lab.repo.head(),
        (real / "config").read_bytes(),
        sorted(p.name for p in (real / "refs" / "heads").iterdir()),
    )
    assert before == after
    assert lab.repo.text("status", "--porcelain") == ""
    assert (git.git_dir / "config").read_bytes() == gitenv.PRISTINE_CONFIG
