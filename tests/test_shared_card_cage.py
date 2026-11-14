"""Shared-card handoffs require the cage belonging to their own fixture."""

import os
from pathlib import Path

import pytest

from tests import shared_card_support as support
from tests.shared_card_support import _submit
from thomas.server import green_checkout, green_handoff
from thomas.tools import cage_shell


@pytest.mark.parametrize("writer", ["_submit", "_write_submission"])
def test_submission_rejects_another_temporary_cage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, writer: str
) -> None:
    blue = tmp_path / "blue"
    other_cage = tmp_path / "another-test" / "cage"
    monkeypatch.setenv("THOMAS_CAGE_ROOT", str(other_cage))

    def unexpected(*args, **kwargs):
        pytest.fail("a foreign cage must be rejected before Git or the handoff writer runs")

    monkeypatch.setattr(support, "_head", unexpected)
    monkeypatch.setattr(green_handoff, "_write_submission", unexpected)
    with pytest.raises(AssertionError, match="their own temporary THOMAS_CAGE_ROOT"):
        if writer == "_submit":
            _submit(blue, "exec-other-cage", {"new.py": "NEW = 1\n"})
        else:
            support._write_submission(blue, "exec-other-cage", "base", "patch", ("new.py",), "chat")
    assert not other_cage.exists()


def test_shared_seed_sets_its_cage_before_git_and_restores_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    previous = str(tmp_path / "previous-cage")
    monkeypatch.setenv(cage_shell.CAGE_ROOT_ENV, previous)
    expected = tmp_path / "shared-card-seed" / "cage"
    calls = []

    class Factory:
        def mktemp(self, name):
            root = tmp_path / name
            root.mkdir()
            return root

    def git(repo, *args):
        assert Path(os.environ[cage_shell.CAGE_ROOT_ENV]) == expected
        assert expected.is_dir()
        assert repo == expected.parent / "blue"
        if args[0] == "init":
            (repo / ".git").mkdir()
        calls.append(args)
        return ""

    monkeypatch.setattr(support, "git", git)
    fixture = support.shared_card_seed.__wrapped__(Factory())
    try:
        assert next(fixture) == expected.parent / "blue"
        assert calls == [("init", "-q", "-b", "dev"), ("add", "-A"), ("commit", "-qm", "init")]
        assert os.environ[cage_shell.CAGE_ROOT_ENV] == previous
    finally:
        fixture.close()
    assert os.environ[cage_shell.CAGE_ROOT_ENV] == previous


def test_shared_green_sets_its_cage_before_checkout_and_restores_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    previous = str(tmp_path / "previous-cage")
    monkeypatch.setenv(cage_shell.CAGE_ROOT_ENV, previous)
    expected = tmp_path / "shared-card-green" / "cage"
    calls = []
    sentinel = object()

    def create(repo, execution_id):
        assert Path(os.environ[cage_shell.CAGE_ROOT_ENV]) == expected
        assert execution_id == "parity-seed"
        calls.append(repo)
        return sentinel

    class Factory:
        def mktemp(self, name):
            root = tmp_path / name
            root.mkdir()
            return root

    monkeypatch.setattr(green_checkout, "create_green", create)
    result = support.shared_card_green.__wrapped__(Factory(), tmp_path / "seed")
    assert result is sentinel
    assert calls == [tmp_path / "seed"]
    assert os.environ[cage_shell.CAGE_ROOT_ENV] == previous
