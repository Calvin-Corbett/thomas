"""A commit that touched a protected overhead file is judged by its own message on a real push.

Proves scripts.forge.gates.core_overhead_guard and scripts.forge.gates._commit_base.
In a real local pre-push run a commit passes with a Thomas-Protected-Files-Approved or Thomas-Breakglass trailer
with a reason (text a committer wrote) or with the promoter's block AND the promoter's own record naming that
commit; an unapproved commit, a forged copy, a partial block or a range that does not explain the file fails.
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


def test_unapproved_edit_still_fails_and_is_listed_by_sha(repo, ledger, monkeypatch, capsys):
    base = _tip(repo)
    sha = _edit(repo, "tweak loop", 1)
    code, out = _push(repo, ledger, monkeypatch, capsys, base, sha)
    assert code == 1 and "no approval in their own message" in out and sha in out


def test_a_promoter_block_with_a_matching_landed_record_approves_its_own_commit(repo, ledger, monkeypatch, capsys):
    base = _tip(repo)
    sha = _edit(repo, _promoter(), 1)
    _record(ledger, sha)
    code, out = _push(repo, ledger, monkeypatch, capsys, base, sha)
    assert code == 0, out


def test_a_promoter_block_with_no_record_is_refused(repo, ledger, monkeypatch, capsys):
    base = _tip(repo)
    sha = _edit(repo, _promoter(), 1)
    code, _out = _push(repo, ledger, monkeypatch, capsys, base, sha)
    assert code == 1


def test_a_copied_promoter_block_on_another_commit_is_refused(repo, ledger, monkeypatch, capsys):
    base = _tip(repo)
    real = _edit(repo, _promoter(), 1)
    _record(ledger, real)
    forged = _edit(repo, _promoter(), 2)
    code, out = _push(repo, ledger, monkeypatch, capsys, base, forged)
    assert code == 1 and forged in out


@pytest.mark.parametrize("status", ["declined", "refused", "error", "held"])
def test_a_record_that_is_not_landed_is_refused(repo, ledger, monkeypatch, capsys, status):
    base = _tip(repo)
    sha = _edit(repo, _promoter(), 1)
    _record(ledger, sha, status=status)
    code, _out = _push(repo, ledger, monkeypatch, capsys, base, sha)
    assert code == 1


def test_an_unreadable_ledger_approves_nothing(repo, tmp_path, monkeypatch, capsys):
    base = _tip(repo)
    sha = _edit(repo, _promoter(), 1)
    code, out = _push(repo, tmp_path / "no-such-ledger", monkeypatch, capsys, base, sha)
    assert code == 1 and "its own record" in out


def test_a_submission_id_that_climbs_out_of_the_ledger_is_refused(repo, ledger, monkeypatch, capsys):
    base = _tip(repo)
    sha = _edit(repo, _promoter("../outbox/x"), 1)
    _record(ledger, sha, sid="x")
    code, _out = _push(repo, ledger, monkeypatch, capsys, base, sha)
    assert code == 1


def test_a_promoter_block_outside_the_real_trailer_block_is_refused(repo, ledger, monkeypatch, capsys):
    base = _tip(repo)
    block = _promoter().split("\n\n", 2)[2]
    sha = _edit(repo, f"self-fix\n\n{block}\nNot a trailer block, just prose after it.\n", 1)
    _record(ledger, sha)
    code, _out = _push(repo, ledger, monkeypatch, capsys, base, sha)
    assert code == 1


@pytest.mark.parametrize("trailer", ["Thomas-Protected-Files-Approved: ticket 12", "Thomas-Breakglass: broken hook"])
def test_an_approval_trailer_with_a_reason_approves_its_own_commit(repo, ledger, monkeypatch, capsys, trailer):
    base = _tip(repo)
    sha = _edit(repo, f"x\n\n{trailer}", 1)
    code, out = _push(repo, ledger, monkeypatch, capsys, base, sha)
    assert code == 0, out


def test_an_approval_trailer_with_no_reason_is_not_an_approval(repo, ledger, monkeypatch, capsys):
    base = _tip(repo)
    sha = _edit(repo, "x\n\nThomas-Protected-Files-Approved:", 1)
    code, _out = _push(repo, ledger, monkeypatch, capsys, base, sha)
    assert code == 1


def test_one_approval_does_not_cover_a_second_unapproved_commit(repo, ledger, monkeypatch, capsys):
    base = _tip(repo)
    approved = _edit(repo, "x\n\nThomas-Breakglass: reason", 1)
    sneaky = _edit(repo, "sneaky edit", 2)
    code, out = _push(repo, ledger, monkeypatch, capsys, base, sneaky)
    assert code == 1 and sneaky in out and approved not in out


def test_a_partial_promoter_block_is_not_an_approval(repo, ledger, monkeypatch, capsys):
    base = _tip(repo)
    sha = _edit(repo, f"x\n\nThomas-Gated: {GATE}", 1)
    _record(ledger, sha)
    code, _out = _push(repo, ledger, monkeypatch, capsys, base, sha)
    assert code == 1


def test_a_range_it_cannot_read_fails_closed(repo, ledger, monkeypatch, capsys):
    sha = _edit(repo, "x\n\nThomas-Breakglass: reason", 1)
    code, _out = _push(repo, ledger, monkeypatch, capsys, "deadbeef" * 5, sha)
    assert code == 1


def test_a_new_branch_with_no_from_ref_is_not_judged_as_a_push(repo, ledger, monkeypatch, capsys):
    sha = _edit(repo, "x\n\nThomas-Breakglass: reason", 1)
    code, _out = _push(repo, ledger, monkeypatch, capsys, "0" * 40, sha)
    assert code == 1


def test_refs_in_the_environment_do_not_turn_a_staged_check_into_a_push(repo, ledger, monkeypatch, capsys):
    base = _tip(repo)
    approved = _edit(repo, "x\n\nThomas-Breakglass: reason", 1)
    (repo / LOOP).write_text("an unapproved staged edit\n")
    _git(repo, "add", "-A")
    monkeypatch.setenv("PRE_COMMIT_FROM_REF", base)
    monkeypatch.setenv("PRE_COMMIT_TO_REF", approved)
    assert _guard(repo, ledger) == 1
    assert "set THOMAS_CORE_OVERHEAD_UNLOCK=1" in capsys.readouterr().out


@pytest.mark.parametrize("how", ["flag", "remote", "hook stage"])
def test_a_staged_protected_edit_fails_even_when_every_push_signal_is_set(repo, ledger, monkeypatch, capsys, how):
    base = _tip(repo)
    approved = _edit(repo, "x\n\nThomas-Breakglass: reason", 1)
    (repo / LOOP).write_text("an unapproved staged edit\n")
    _git(repo, "add", "-A")
    monkeypatch.setenv("PRE_COMMIT_FROM_REF", base)
    monkeypatch.setenv("PRE_COMMIT_TO_REF", approved)
    extra = ("--push",) if how == "flag" else ()
    if how == "remote":
        monkeypatch.setenv("PRE_COMMIT_REMOTE_NAME", "origin")
        monkeypatch.setenv("PRE_COMMIT_REMOTE_URL", "x")
    if how == "hook stage":
        monkeypatch.setenv("PRE_COMMIT_HOOK_STAGE", "pre-push")
    assert _guard(repo, ledger, *extra) == 1
    assert "set THOMAS_CORE_OVERHEAD_UNLOCK=1" in capsys.readouterr().out


def test_a_range_that_does_not_explain_the_protected_file_fails_closed(repo, ledger, monkeypatch, capsys):
    base = _tip(repo)
    sha = _edit(repo, "x\n\nThomas-Breakglass: reason", 1, path=OTHER)
    code, out = _push(repo, ledger, monkeypatch, capsys, base, sha)
    assert code == 1 and LOOP in out and "does not account for" in out
