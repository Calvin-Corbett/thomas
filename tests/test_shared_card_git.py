"""Focused subprocess-free contract tests for the shared-card Git read cache."""

import os
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

SHA1 = "a" * 40
SHA256 = "b" * 64


class FakeRun:
    def __init__(self):
        self.calls = []
        self.results = []
        self.returncode = 0
        self.error = None

    def __call__(self, args, *pos, **kwargs):
        self.calls.append(deepcopy((args, pos, kwargs)))
        if self.error is not None:
            raise self.error
        number = len(self.calls)
        stdout, stderr = f"stdout-{number}\n", f"stderr-{number}\n"
        if not (kwargs.get("text") or kwargs.get("encoding") or kwargs.get("universal_newlines")):
            stdout, stderr = stdout.encode(), stderr.encode()
        result = subprocess.CompletedProcess(deepcopy(args), self.returncode, stdout, stderr)
        self.results.append(result)
        return result


def make_repo(path):
    (path / ".git" / "info").mkdir(parents=True)
    (path / ".git" / "config").write_text("[core]\n\tbare = false\n", encoding="utf-8")
    (path / ".git" / "info" / "attributes").write_text("*.py text\n", encoding="utf-8")
    return path


@pytest.fixture
def repo(tmp_path):
    return make_repo(tmp_path / "repo")


@pytest.fixture
def runner(monkeypatch, tmp_path):
    from tests.shared_card_git import GitReads

    for name in list(os.environ):
        if name.startswith("GIT_"):
            monkeypatch.delenv(name)
    home = tmp_path / "git-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / ".gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    fake = FakeRun()
    # Even an accidental subprocess.run call in these tests cannot launch Git.
    cached = GitReads(fake)
    cached.executable = None
    monkeypatch.setattr(subprocess, "run", cached)
    return fake


def read(repo, *command, **kwargs):
    options = {"cwd": str(repo), "capture_output": True, "text": True, "check": False}
    options.update(kwargs)
    return subprocess.run(["git", *command], **options)


@pytest.mark.parametrize("oid", [SHA1, SHA256], ids=["sha1", "sha256"])
def test_immutable_reads_are_cached(repo, runner, oid):
    cases = [
        (("diff-tree", "--no-commit-id", "--name-status", "-r", "{oid}", "{other}"), None),
        (("ls-tree", "-r", "-z", "{oid}"), None),
        (
            (
                "--attr-source={oid}",
                "diff",
                "--no-textconv",
                "--no-ext-diff",
                "--text",
                "{oid}",
                "{other}",
                "--",
                "a.py",
            ),
            None,
        ),
        (
            (
                "--attr-source={oid}",
                "diff",
                "--no-textconv",
                "--no-ext-diff",
                "--numstat",
                "--no-renames",
                "{oid}",
                "{other}",
            ),
            None,
        ),
        (("rev-parse", "--verify", "--quiet", "{oid}:README.md"), None),
        (("show", "{oid}:README.md"), None),
        (("cat-file", "blob", "{oid}:README.md"), None),
        (("cat-file", "--batch-check"), "{oid}:README.md\n{other}:dir/a b.py\n"),
    ]
    values = {"oid": oid, "other": "c" * len(oid)}
    for command, input_text in cases:
        before = len(runner.calls)
        command = tuple(arg.format(**values) for arg in command)
        kwargs = {} if input_text is None else {"input": input_text.format(**values)}
        first = read(repo, *command, **kwargs)
        second = read(repo, *command, **kwargs)
        assert len(runner.calls) == before + 1, command
        assert first is not second
        assert (second.args, second.returncode, second.stdout, second.stderr) == (
            first.args,
            first.returncode,
            first.stdout,
            first.stderr,
        )
        assert runner.calls[before] == (
            ["git", *command],
            (),
            {"cwd": str(repo), "capture_output": True, "text": True, "check": False, **kwargs},
        )


def test_unsupported_commands_always_reach_real_run(repo, runner):
    cases = [
        (("show", "HEAD:README.md"), None),
        (("--attr-source=HEAD", "diff", "--no-textconv", "--no-ext-diff", SHA1, SHA256), None),
        (("--attr-source=" + SHA1,), None),
        (("show", "main:README.md"), None),
        (("show", "aaaaaaa:README.md"), None),
        (("show", "z" * 40 + ":README.md"), None),
        (("rev-parse", "--verify", "--quiet", "HEAD:README.md"), None),
        (("ls-tree", "-r", "HEAD"), None),
        (("ls-tree", "-r", "a" * 39), None),
        (("ls-tree", "-r", "a" * 65), None),
        (("diff-tree", "-r", SHA1, "HEAD"), None),
        (("diff-tree", "-r", "HEAD", SHA1), None),
        (("status", "--porcelain"), None),
        (("diff", "--cached"), None),
        (("diff",), None),
        (("ls-files", "-s"), None),
        (("cat-file", "--filters", SHA1 + ":README.md"), None),
        (("cat-file", "blob", "HEAD:README.md"), None),
        (("cat-file", "--batch-check"), SHA1 + ":README.md\nHEAD:README.md\n"),
        (("cat-file", "--batch-check"), "HEAD:README.md\n" + SHA1 + ":README.md\n"),
        (("cat-file", "--batch-check"), "aaaaaaa:README.md\n"),
        (("commit", "-qm", "not executed"), None),
        (("update-ref", "refs/heads/main", SHA1), None),
        (("checkout", SHA1), None),
        (("config", "core.autocrlf", "true"), None),
        (("show", "--textconv", SHA1 + ":README.md"), None),
        (("show", "--output=card.patch", SHA1 + ":README.md"), None),
        (("show", "--output", "card.patch", SHA1 + ":README.md"), None),
        (("rev-parse", "--git-path", SHA1 + ":README.md"), None),
        (("rev-parse", "--verify", SHA1 + ":README.md", "--show-prefix"), None),
        (("ls-tree", "-r", SHA1, "HEAD"), None),
        (("ls-tree", "--format=%(objectname)", SHA1), None),
        (("diff", "--output=card.patch", SHA1, SHA256), None),
        (("diff", "--ext-diff", SHA1, SHA256), None),
        (("diff", "--textconv", SHA1, SHA256), None),
        (("diff", SHA1, SHA256, "HEAD"), None),
        (("diff-tree", "--output=card.patch", "-r", SHA1, SHA256), None),
        (("cat-file", "--batch-check", "--filters"), SHA1 + ":README.md\n"),
        (("cat-file", "--batch-check=unknown"), SHA1 + ":README.md\n"),
    ]
    for command, input_text in cases:
        before = len(runner.calls)
        kwargs = {} if input_text is None else {"input": input_text}
        first = read(repo, *command, **kwargs)
        second = read(repo, *command, **kwargs)
        assert len(runner.calls) == before + 2, command
        assert first.stdout != second.stdout, command


@pytest.mark.parametrize("redirect", [{}, {"stdout": subprocess.PIPE}, {"stdout": subprocess.DEVNULL}])
def test_uncaptured_streams_always_reach_real_run(repo, runner, redirect):
    for _ in range(2):
        subprocess.run(["git", "show", SHA1 + ":README.md"], cwd=str(repo), **redirect)
    assert len(runner.calls) == 2


def test_mutable_attribute_source_is_not_cached(repo, runner):
    for _ in range(2):
        subprocess.run(
            ["git", "--attr-source=HEAD", "show", SHA1 + ":README.md"],
            cwd=str(repo),
            capture_output=True,
            text=True,
        )
    assert len(runner.calls) == 2


def test_diff_without_pinned_attributes_is_not_cached(repo, runner):
    command = ("diff", "--no-textconv", "--no-ext-diff", SHA1, SHA256)
    read(repo, *command)
    (repo / ".gitattributes").write_text("*.py binary\n", encoding="utf-8")
    read(repo, *command)
    assert len(runner.calls) == 2


@pytest.mark.parametrize("marker", ["refs/replace/object", "packed-refs", "info/grafts", "shallow"])
def test_rewritten_object_graph_is_not_cached(repo, runner, marker):
    command = ("show", f"{SHA1}:README.md")
    read(repo, *command)
    path = repo / ".git" / marker
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{SHA256} refs/replace/{SHA1}\n", encoding="utf-8")
    read(repo, *command)
    read(repo, *command)
    assert len(runner.calls) == 3


def test_non_git_command_is_not_cached(repo, runner):
    for _ in range(2):
        subprocess.run(["echo", "show", SHA1 + ":README.md"], cwd=str(repo))
    assert len(runner.calls) == 2


def test_exact_arguments_are_part_of_key(repo, runner):
    commands = [("show", SHA1 + ":a.py"), ("show", SHA1 + ":b.py")]
    for command in commands:
        read(repo, *command)
        read(repo, *command)
    assert len(runner.calls) == 2


def test_cwd_is_part_of_key(repo, runner, tmp_path):
    other = make_repo(tmp_path / "other")
    for directory in (repo, other):
        read(directory, "show", SHA1 + ":README.md")
        read(directory, "show", SHA1 + ":README.md")
    assert len(runner.calls) == 2


def test_subprocess_settings_are_part_of_key(repo, runner):
    cases = [
        ("text", True, False),
        ("encoding", "utf-8", "ascii"),
        ("errors", "strict", "replace"),
        ("check", False, True),
        ("timeout", 1, 2),
        ("env", {"GIT_CONFIG_NOSYSTEM": "1"}, {"GIT_CONFIG_NOSYSTEM": "0"}),
    ]
    for name, first, second in cases:
        command = ("show", SHA1 + ":" + name)
        before = len(runner.calls)
        read(repo, *command, **{name: first})
        read(repo, *command, **{name: second})
        assert len(runner.calls) == before + 2, name
        assert runner.calls[before][2][name] == first
        assert runner.calls[before + 1][2][name] == second


def test_mutated_env_mapping_invalidates(repo, runner):
    env = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.autocrlf", "GIT_CONFIG_VALUE_0": "false"}
    read(repo, "show", SHA1 + ":README.md", env=env)
    env["GIT_CONFIG_VALUE_0"] = "true"
    read(repo, "show", SHA1 + ":README.md", env=env)
    assert len(runner.calls) == 2


def test_inherited_git_settings_invalidate(repo, runner, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.autocrlf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "false")
    read(repo, "show", SHA1 + ":README.md")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "true")
    read(repo, "show", SHA1 + ":README.md")
    assert len(runner.calls) == 2
