"""A command-line range, an untrusted ledger and a merge are judged strictly; refs alone never make a push.

Proves scripts.forge.gates.core_overhead_guard and scripts.forge.gates._commit_base.
A range on the command line takes only a verified promoter record; a ledger inside or around the checkout is
refused; a merge that carries a protected edit needs approval; refs in the environment do not make a push.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._core_overhead_support import (
    LOOP,
    OTHER,
    make_ledger,
    make_repo,
)
from tests._core_overhead_support import (
    edit as _edit,
)
from tests._core_overhead_support import (
    git as _git,
)
from tests._core_overhead_support import (
    guard as _guard,
)
from tests._core_overhead_support import (
    load as _load,
)
from tests._core_overhead_support import (
    promoter as _promoter,
)
from tests._core_overhead_support import (
    push as _push,
)
from tests._core_overhead_support import (
    record as _record,
)
from tests._core_overhead_support import (
    tip as _tip,
)

GATE = "owner-approved/windows-sign-in"


@pytest.fixture
def repo(tmp_path, monkeypatch):
    return make_repo(tmp_path, monkeypatch)


@pytest.fixture
def ledger(tmp_path):
    return make_ledger(tmp_path)


def test_a_range_on_the_command_line_takes_no_trailer_a_committer_wrote(repo, ledger, capsys):
    base = _tip(repo)
    sha = _edit(repo, "x\n\nThomas-Breakglass: reason", 1)
    assert _guard(repo, ledger, "--base", base, "--head", sha, files=()) == 1
    assert "takes only that record" in capsys.readouterr().out


def test_a_range_on_the_command_line_takes_a_verified_promoter_record(repo, ledger, capsys):
    base = _tip(repo)
    sha = _edit(repo, _promoter(), 1)
    _record(ledger, sha)
    assert _guard(repo, ledger, "--base", base, "--head", sha, files=()) == 0, capsys.readouterr().out


def test_refs_and_a_remote_pair_in_the_environment_are_a_real_push(repo, ledger, monkeypatch, capsys):
    base = _tip(repo)
    sha = _edit(repo, "x\n\nThomas-Breakglass: reason", 1)
    monkeypatch.setenv("PRE_COMMIT_FROM_REF", base)
    monkeypatch.setenv("PRE_COMMIT_TO_REF", sha)
    monkeypatch.setenv("PRE_COMMIT_REMOTE_NAME", "origin")
    monkeypatch.setenv("PRE_COMMIT_REMOTE_URL", "x")
    assert _guard(repo, ledger) == 0, capsys.readouterr().out


def test_refs_alone_are_not_a_push(repo, ledger, monkeypatch, capsys):
    base = _tip(repo)
    sha = _edit(repo, "x\n\nThomas-Breakglass: reason", 1)
    monkeypatch.setenv("PRE_COMMIT_FROM_REF", base)
    monkeypatch.setenv("PRE_COMMIT_TO_REF", sha)
    assert _guard(repo, ledger) == 1
    assert "set THOMAS_CORE_OVERHEAD_UNLOCK=1" in capsys.readouterr().out


def _landed_as_a_promoter_commit(repo: Path, where: Path, monkeypatch) -> str:
    """A promoter commit whose perfect record sits in ``where``/outbox, with the push refs in the environment."""
    (where / "outbox").mkdir(parents=True, exist_ok=True)
    base = _tip(repo)
    sha = _edit(repo, _promoter(), 1)
    _record(where, sha)
    monkeypatch.setenv("PRE_COMMIT_FROM_REF", base)
    monkeypatch.setenv("PRE_COMMIT_TO_REF", sha)
    return sha


def test_a_ledger_inside_the_checkout_is_refused_even_with_a_perfect_record(repo, monkeypatch, capsys):
    inside = repo / "ledger"
    _landed_as_a_promoter_commit(repo, inside, monkeypatch)
    assert _guard(repo, inside, "--push") == 1
    assert "ignoring the --ledger promoter ledger" in capsys.readouterr().err


def test_a_ledger_that_holds_the_checkout_is_refused(repo, monkeypatch):
    _landed_as_a_promoter_commit(repo, repo.parent, monkeypatch)
    assert _guard(repo, repo.parent, "--push") == 1


def test_a_relative_ledger_is_refused(repo, ledger, monkeypatch, capsys):
    _landed_as_a_promoter_commit(repo, ledger, monkeypatch)
    monkeypatch.chdir(ledger.parent)
    assert _guard(repo, "ledger", "--push") == 1
    assert "not an absolute path" in capsys.readouterr().err


def test_an_environment_override_pointing_into_the_checkout_is_ignored(repo, monkeypatch):
    inside = repo / "ledger"
    _landed_as_a_promoter_commit(repo, inside, monkeypatch)
    monkeypatch.setenv("THOMAS_PROMOTER_LEDGER", str(inside))
    mod = _load()
    mod.ROOT = repo
    monkeypatch.setattr(mod, "_default_ledger", lambda: None)
    manifest = str(repo / "docs" / "core_overhead_manifest.json")
    assert mod.run(["--manifest", manifest, "--push", LOOP]) == 1


def test_a_ledger_in_the_main_checkout_of_a_linked_worktree_is_refused(repo, tmp_path, monkeypatch):
    link = tmp_path / "linked"
    _git(repo, "worktree", "add", "-q", str(link), "-b", "linked")
    mod = _load()
    mod.ROOT = link
    monkeypatch.setattr(mod, "_default_ledger", lambda: None)
    assert mod._trusted_ledger(str(repo / "ledger")) is None


def test_the_promoter_path_is_off_where_the_host_has_no_ledger(repo, monkeypatch):
    mod = _load()
    mod.ROOT = repo
    monkeypatch.setattr(mod.os, "name", "posix")
    assert mod._trusted_ledger(None) is None


def test_a_trusted_ledger_outside_the_checkout_works_and_is_resolved(repo, ledger):
    mod = _load()
    mod.ROOT = repo
    assert mod._trusted_ledger(str(ledger)) == ledger.resolve()


def test_the_judge_takes_a_test_only_ledger_directly(repo, ledger):
    base = _tip(repo)
    sha = _edit(repo, _promoter(), 1)
    _record(ledger, sha)
    mod = _load()
    mod.ROOT = repo
    bad, explained = mod._judge_range(base, sha, {LOOP}, ledger, text_trailers=False)
    assert bad == [] and explained == {LOOP}
    bad, _ = mod._judge_range(base, sha, {LOOP}, None, text_trailers=False)
    assert bad == [sha]


def _merge_with_a_hand_written_protected_file(repo: Path, message: str) -> tuple[str, str]:
    base = _tip(repo)
    trunk = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    _git(repo, "checkout", "-q", "-b", "side")
    _edit(repo, "side\n\nThomas-Breakglass: reason", "side")
    _git(repo, "checkout", "-q", trunk)
    _edit(repo, "trunk\n\nThomas-Breakglass: reason", "trunk")
    _git(repo, "merge", "-q", "side", check=False)
    (repo / LOOP).write_text("written by hand inside the merge\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", message)
    assert len(_git(repo, "rev-list", "--parents", "-n", "1", "HEAD").split()) == 3
    return base, _tip(repo)


def test_a_merge_that_carries_a_protected_edit_is_refused_without_approval(repo, ledger, monkeypatch, capsys):
    base, merge = _merge_with_a_hand_written_protected_file(repo, "merge side")
    code, out = _push(repo, ledger, monkeypatch, capsys, base, merge)
    assert code == 1 and merge in out


def test_a_merge_that_carries_a_protected_edit_passes_with_approval(repo, ledger, monkeypatch, capsys):
    base, merge = _merge_with_a_hand_written_protected_file(repo, "merge side\n\nThomas-Breakglass: reason")
    code, out = _push(repo, ledger, monkeypatch, capsys, base, merge)
    assert code == 0, out


def test_no_range_means_staged_mode_fails_closed(repo, ledger, capsys):
    assert _guard(repo, ledger) == 1
    assert "set THOMAS_CORE_OVERHEAD_UNLOCK=1" in capsys.readouterr().out


def test_the_unlock_switch_still_passes_a_commit_time_edit(repo, ledger, monkeypatch):
    monkeypatch.setenv("THOMAS_CORE_OVERHEAD_UNLOCK", "1")
    assert _guard(repo, ledger) == 0
