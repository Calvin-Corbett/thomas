"""Mutable external Git settings must remain visible through both fixture caches."""

import os
import subprocess
from pathlib import Path

import pytest

from tests.green_support import git
from tests.shared_card_git import GitReads
from tests.shared_card_support import _submit, blue, shared_card_seed  # noqa: F401


@pytest.mark.parametrize("source", ["include", "attributes"])
def test_submission_observes_external_settings(blue, source):
    external = blue.parent / "external-settings"
    if source == "include":
        external.write_text("[diff]\n\tnoprefix = true\n", encoding="utf-8")
        git(blue, "config", "include.path", str(external))
    else:
        external.write_text("README.md -diff\n", encoding="utf-8")
        git(blue, "config", "core.attributesFile", str(external))
    files = {"README.md": "external configuration must stay observable\n"}
    first = (_submit(blue, "external-first", files) / "change.patch").read_bytes()
    external.write_text("[diff]\n\tnoprefix = false\n" if source == "include" else "", encoding="utf-8")
    second = (_submit(blue, "external-second", files) / "change.patch").read_bytes()
    assert first != second
    assert b"--- a/README.md" in second
    if source == "include":
        assert b"--- README.md" in first
    else:
        assert b"GIT binary patch" in first


def test_submission_observes_external_ignore_file(blue):
    external = blue.parent / "external-ignore"
    external.write_text("new.py\n", encoding="utf-8")
    git(blue, "config", "core.excludesFile", str(external))
    files = {"README.md": "a tracked edit\n", "new.py": "NEW = 1\n"}
    first = (_submit(blue, "ignore-first", files) / "change.patch").read_bytes()
    external.write_text("", encoding="utf-8")
    second = (_submit(blue, "ignore-second", files) / "change.patch").read_bytes()
    assert b"new.py" not in first
    assert b"new.py" in second
    assert first != second


@pytest.mark.parametrize("cache_kind", ["submission", "reads"])
def test_external_diff_order_stays_observable(blue, cache_kind):
    order = blue.parent / "diff-order"
    order.write_text("README.md\nthomas/fix_me.py\n", encoding="utf-8", newline="\n")
    git(blue, "config", "diff.orderFile", str(order))
    base = git(blue, "rev-parse", "HEAD")
    files = {"README.md": "ordered edit\n", "thomas/fix_me.py": "VALUE = 2\n"}
    if cache_kind == "reads":
        for name, text in files.items():
            (blue / name).write_text(text, encoding="utf-8")
        git(blue, "add", "-A")
        git(blue, "commit", "-qm", "ordered changes")
        tip = git(blue, "rev-parse", "HEAD")
        cache = GitReads(subprocess.run)

    def observe(execution):
        if cache_kind == "submission":
            return (_submit(blue, execution, files) / "change.patch").read_bytes()
        return cache(
            ["git", f"--attr-source={base}", "diff", "--no-ext-diff", "--no-textconv", base, tip],
            cwd=blue,
            capture_output=True,
            check=True,
        ).stdout

    first = observe("order-first")
    order.write_text("thomas/fix_me.py\nREADME.md\n", encoding="utf-8", newline="\n")
    second = observe("order-second")
    readme = b"diff --git a/README.md"
    code = b"diff --git a/thomas/fix_me.py"
    assert first.index(readme) < first.index(code)
    assert second.index(code) < second.index(readme)
    assert first != second


@pytest.mark.parametrize("cache_kind", ["submission", "reads"])
def test_object_replacements_are_not_hidden(blue, cache_kind):
    base = git(blue, "rev-parse", "HEAD")
    (blue / "README.md").write_text("replacement content\n", encoding="utf-8")
    git(blue, "add", "README.md")
    git(blue, "commit", "-qm", "replacement tree")
    tip = git(blue, "rev-parse", "HEAD")
    cache = GitReads(subprocess.run)

    def observe(execution):
        if cache_kind == "submission":
            return (_submit(blue, execution, {"README.md": "requested content\n"}) / "change.patch").read_bytes()
        return cache(["git", "show", tip + ":README.md"], cwd=blue, capture_output=True, check=True).stdout

    first = observe("replacement-first")
    git(blue, "replace", tip, base)
    second = observe("replacement-second")
    assert first != second
    assert b"replacement content" in first
    assert b"blue" in second


@pytest.mark.parametrize("source", ["include", "attributes", "command-attributes", "command-include"])
def test_pinned_diff_observes_external_settings(blue, source):
    base = git(blue, "rev-parse", "HEAD")
    (blue / "README.md").write_text("a different tree\n", encoding="utf-8")
    git(blue, "add", "README.md")
    git(blue, "commit", "-qm", "second tree")
    tip = git(blue, "rev-parse", "HEAD")
    external = blue.parent / "external-diff-settings"
    options = []
    if source in {"include", "command-include"}:
        external.write_text("[diff]\n\tnoprefix = true\n", encoding="utf-8")
        if source == "command-include":
            options = ["-c", f"include.path={external}"]
        else:
            git(blue, "config", "include.path", str(external))
    else:
        external.write_text("README.md -diff\n", encoding="utf-8")
        if source == "command-attributes":
            options = ["-c", f"core.attributesFile={external}"]
        else:
            git(blue, "config", "core.attributesFile", str(external))
    args = ["git", *options, f"--attr-source={base}", "diff", "--no-ext-diff", "--no-textconv", base, tip]

    def run(args, **kwargs):
        return subprocess.run(args, **{**kwargs, "env": dict(kwargs["env"])})

    cache = GitReads(run)
    env = dict(os.environ)
    first = cache(args, cwd=blue, env=env, capture_output=True, text=True, check=True).stdout
    external.write_text("[diff]\n\tnoprefix = false\n" if "include" in source else "", encoding="utf-8")
    second = cache(args, cwd=blue, env=env, capture_output=True, text=True, check=True).stdout
    assert first != second
    assert "--- a/README.md" in second
    if "include" in source:
        assert "--- README.md" in first
    else:
        assert "Binary files" in first


@pytest.mark.parametrize("setting", ["attributes", "ignore", "worktree", "replace"])
def test_submission_observes_other_git_inputs(blue, monkeypatch, setting):
    files = {"README.md": "a tracked edit\n", "new.py": "NEW = 1\n"}
    external = blue.parent / "extra-git-input"
    if setting in {"attributes", "ignore"}:
        config_home = blue.parent / "xdg"
        (config_home / "git").mkdir(parents=True)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
        external = config_home / "git" / ("attributes" if setting == "attributes" else "ignore")
        external.write_text("README.md -diff\n" if setting == "attributes" else "new.py\n", encoding="utf-8")
    elif setting == "worktree":
        git(blue, "config", "extensions.worktreeConfig", "true")
        git(blue, "config", "--worktree", "diff.noprefix", "true")
    else:
        base = git(blue, "rev-parse", "HEAD")
        (blue / "README.md").write_text("replacement base\n", encoding="utf-8")
        git(blue, "add", "README.md")
        tree = git(blue, "write-tree")
        replacement = git(blue, "commit-tree", tree, "-m", "replacement")
        git(blue, "reset", "--hard", base)
        git(blue, "replace", base, replacement)
    first = (_submit(blue, "extra-first", files) / "change.patch").read_bytes()
    if setting in {"attributes", "ignore"}:
        external.write_text("", encoding="utf-8")
    elif setting == "worktree":
        git(blue, "config", "--worktree", "diff.noprefix", "false")
    else:
        git(blue, "replace", "-d", base)
    second = (_submit(blue, "extra-second", files) / "change.patch").read_bytes()
    assert first != second
    assert b"--- a/README.md" in second
    if setting == "attributes":
        assert b"GIT binary patch" in first
    elif setting == "ignore":
        assert b"new.py" not in first
        assert b"new.py" in second
    elif setting == "worktree":
        assert b"--- README.md" in first
    else:
        assert b"-replacement base" in first
        assert b"-blue" in second
