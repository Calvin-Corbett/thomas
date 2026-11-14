"""Cache invalidation, stream settings and failed Git reads stay observable."""

import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

from tests.test_shared_card_git import SHA1, read, repo, runner  # noqa: F401


@pytest.mark.parametrize("relative", [".git/config", ".git/info/attributes"])
def test_repository_settings_changes_invalidate(repo, runner, relative):
    read(repo, "show", SHA1 + ":README.md")
    path = repo / Path(relative)
    with path.open("a", encoding="utf-8") as stream:
        stream.write("\n# changed settings with a different file size\n")
    read(repo, "show", SHA1 + ":README.md")
    assert len(runner.calls) == 2


@pytest.mark.parametrize("binary", [False, True])
@pytest.mark.parametrize("option", ["--batch-check", "--batch-check=%(objectname)"])
@pytest.mark.parametrize("mixed", [False, True])
def test_successful_missing_batch_result_is_not_cached(repo, runner, binary, option, mixed):
    cached = subprocess.run
    real = cached.real_run
    batch = (SHA1 + ":present\n" if mixed else "") + SHA1 + ":missing\n"

    def missing(*args, **kwargs):
        result = real(*args, **kwargs)
        text = (SHA1 + " blob 4\n" if mixed else "") + SHA1 + ":missing missing\n"
        result.stdout = text.encode() if binary else text
        return result

    cached.real_run = missing
    for _ in range(2):
        result = read(repo, "cat-file", option, input=batch, text=not binary)
        assert result.returncode == 0
    assert len(runner.calls) == 2
    cached.real_run = real
    read(repo, "cat-file", option, input=batch, text=not binary)
    read(repo, "cat-file", option, input=batch, text=not binary)
    assert len(runner.calls) == 3


@pytest.mark.parametrize("explicit_env", [False, True])
def test_external_configuration_changes_invalidate(repo, runner, monkeypatch, explicit_env):
    config = repo / "global-config"
    config.write_text("[diff]\n\tnoprefix = false\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    options = {"env": dict(__import__("os").environ)} if explicit_env else {}
    read(repo, "show", SHA1 + ":README.md", **options)
    config.write_text("[diff]\n\tnoprefix = true\n", encoding="utf-8")
    read(repo, "show", SHA1 + ":README.md", **options)
    assert len(runner.calls) == 2


@pytest.mark.parametrize("section", ["include", 'includeIf "gitdir:./"'])
@pytest.mark.parametrize("external", [False, True])
def test_configuration_includes_bypass_cache(repo, runner, section, external):
    config = Path(__import__("os").environ["GIT_CONFIG_GLOBAL"]) if external else repo / ".git/config"
    with config.open("a", encoding="utf-8") as stream:
        stream.write(f"\n[{section}]\n\tpath = included-config\n")
    for _ in range(2):
        read(repo, "show", SHA1 + ":README.md")
    assert len(runner.calls) == 2


def test_batch_input_is_part_of_key(repo, runner):
    for spec in (SHA1 + ":a.py\n", SHA1 + ":b.py\n"):
        read(repo, "cat-file", "--batch-check", input=spec)
        read(repo, "cat-file", "--batch-check", input=spec)
    assert len(runner.calls) == 2


def test_binary_batch_input_is_cached(repo, runner):
    spec = (SHA1 + ":a.py\n").encode()
    first = read(repo, "cat-file", "--batch-check", input=spec, text=False)
    second = read(repo, "cat-file", "--batch-check", input=spec, text=False)
    assert len(runner.calls) == 1
    assert isinstance(second.stdout, bytes)
    assert second.stdout == first.stdout


def test_positional_settings_are_forwarded_and_distinguished(repo, runner):
    args = ["git", "show", SHA1 + ":README.md"]
    for bufsize in (0, 1):
        subprocess.run(args, bufsize, cwd=str(repo), text=True)
    assert len(runner.calls) == 2
    assert [call[1] for call in runner.calls] == [(0,), (1,)]


def test_nonzero_results_are_not_cached(repo, runner):
    runner.returncode = 1
    for _ in range(2):
        assert read(repo, "show", SHA1 + ":missing").returncode == 1
    assert len(runner.calls) == 2
    runner.returncode = 0
    read(repo, "show", SHA1 + ":missing")
    read(repo, "show", SHA1 + ":missing")
    assert len(runner.calls) == 3


@pytest.mark.parametrize(
    "error",
    [subprocess.CalledProcessError(1, ["git"]), subprocess.TimeoutExpired(["git"], 1), OSError("no executable")],
)
def test_exceptions_are_not_cached(repo, runner, error):
    runner.error = error
    for _ in range(2):
        with pytest.raises(type(error)):
            read(repo, "show", SHA1 + ":README.md", check=True)
    assert len(runner.calls) == 2


@pytest.mark.parametrize("setting", ["include.path=external", "diff.noprefix=true", "core.attributesFile=external"])
def test_untracked_command_configuration_bypasses_cache(repo, runner, setting):
    first = read(repo, "-c", setting, "show", SHA1 + ":README.md")
    second = read(repo, "-c", setting, "show", SHA1 + ":README.md")
    assert first.stdout != second.stdout
    assert len(runner.calls) == 2


@pytest.mark.parametrize("binary", [False, True])
def test_result_mutation_does_not_leak_into_cache(repo, runner, binary):
    command = ("show", SHA1 + ":README.md")
    first = read(repo, *command, text=not binary)
    expected = (deepcopy(first.args), first.returncode, first.stdout, first.stderr)
    first.args.append("caller mutation")
    first.returncode, first.stdout, first.stderr = 99, "changed", "changed"
    second = read(repo, *command, text=not binary)
    assert second is not first
    assert (second.args, second.returncode, second.stdout, second.stderr) == expected
    second.stdout = "also changed"
    third = read(repo, *command, text=not binary)
    assert third is not second
    assert (third.args, third.returncode, third.stdout, third.stderr) == expected
    assert len(runner.calls) == 1
