"""Which waiting self-fixes may share one Windows sign-in, each checked on top of the one before.

Your decision, 2026-10-08: "Yes, batch cards". When two or more reviewed self-fixes are waiting, the promoter puts up
to five of them on one card, the oldest first (scripts/cage/card_chain.py). Each is derived on the tree the one before
it leaves, and every check a single card runs is run on it there. Never on a shared card: a change with a file that
guards Thomas (it keeps its own cards), a change with no chat to show its card, a change you were already asked about
on its own, and a change whose files do not all fit. A change that fails only on top of another waits for a later
card; one that fails by itself on dev is refused in its own words, as it would be alone. These form the chain and ask
nothing; the sign-in is tested with the promoter (tests/test_one_sign_in_lands_several_self_fixes.py).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from scripts.cage import card_chain
from scripts.cage import self_change_checks as checks
from scripts.cage import self_change_promoter as sp

from tests.green_support import git
from tests.shared_card_support import _submit, blue, shared_card_seed  # noqa: F401
from tests.test_a_self_fix_lands_only_when_you_approve import Asker, _outbox, _promoter, pins  # noqa: F401
from thomas.server.self_change_status import RUNNING_COPY_DIRTY
from thomas.tools import cage_shell, trusted_card

CARDS = trusted_card.load_catalogue()


def _form(promoter: sp.Promoter) -> tuple[list[card_chain.Member], list[sp.Outcome]]:
    """The chain the promoter would put on one card now, and the verdicts that forming it gave."""
    done: list[sp.Outcome] = []
    members = card_chain.open_members(promoter, promoter.pending(), done)
    enforced = sp._enforced(CARDS, promoter.repo)
    return card_chain.form(promoter, members, promoter._dev(), CARDS, enforced, done), done


def _names(chain: list[card_chain.Member]) -> list[str]:
    return [m.sub_dir.name for m in chain]


def _waiting(sub: Path) -> bool:
    """Still in the inbox, with no verdict: nothing was decided about it."""
    return sub.is_dir() and not (cage_shell.cage_root() / "outbox" / f"{sub.name}.verdict.json").exists()


def _no_chat(blue: Path, execution_id: str, files: dict[str, str]) -> Path:
    sub = _submit(blue, execution_id, files, chat="")
    assert sub is not None
    return sub


def test_one_waiting_hand_in_forms_no_shared_card(blue: Path, pins: Path) -> None:
    sub = _submit(blue, "exec-alone", {"thomas/fix_me.py": "VALUE = 2\n"})

    chain, done = _form(_promoter(blue, pins, Asker()))

    assert len(chain) < CARDS.LIST_KINDS[card_chain.SHARED].min_rows and done == []
    assert _waiting(sub)


def test_each_link_is_derived_on_the_one_before(blue: Path, pins: Path) -> None:
    lines = "".join(f"LINE_{n} = {n}\n" for n in range(12))
    (blue / "thomas" / "lines.py").write_text(lines, encoding="utf-8")
    git(blue, "add", "-A")
    git(blue, "commit", "-qm", "a file two changes edit")
    top = _submit(blue, "exec-top", {"thomas/lines.py": lines.replace("LINE_0 = 0", "LINE_0 = 100")})
    bottom = _submit(blue, "exec-bottom", {"thomas/lines.py": lines.replace("LINE_11 = 11", "LINE_11 = 111")})

    chain, done = _form(_promoter(blue, pins, Asker()))

    assert _names(chain) == [top.name, bottom.name] and done == []
    first, second = chain
    assert first.base == git(blue, "rev-parse", "dev") and second.base == first.tree
    both = git(blue, "show", f"{second.tree}:thomas/lines.py")
    assert "LINE_0 = 100" in both and "LINE_11 = 111" in both, "the second change applies to the first one's result"
    assert second.row == {"files": [["thomas/lines.py", "M", 1, 1]]}, "its line shows its own diff, which is what lands"


def test_a_self_fix_with_a_guarded_file_never_shares_a_card(blue: Path, pins: Path) -> None:
    a = _submit(blue, "exec-g-a", {"thomas/a.py": "A = 1\n"})
    guarded = _submit(blue, "exec-g-b", {"scripts/cage/new_rule.py": "RULE = 1\n", "thomas/b.py": "B = 1\n"})
    c = _submit(blue, "exec-g-c", {"thomas/c.py": "C = 1\n"})

    chain, done = _form(_promoter(blue, pins, Asker()))

    assert _names(chain) == [a.name, c.name] and done == []
    assert _waiting(guarded), "it keeps its own cards, later"


def test_a_guarded_self_fix_at_the_head_forms_no_card(blue: Path, pins: Path) -> None:
    """The oldest decides: when it cannot share, it is asked alone first, and nothing newer goes ahead of it."""
    guarded = _submit(blue, "exec-gh-a", {"scripts/cage/new_rule.py": "RULE = 1\n"})
    _submit(blue, "exec-gh-b", {"thomas/b.py": "B = 1\n"})
    _submit(blue, "exec-gh-c", {"thomas/c.py": "C = 1\n"})

    chain, done = _form(_promoter(blue, pins, Asker()))

    assert chain == [] and done == []
    assert _waiting(guarded)


def test_a_self_fix_with_no_chat_never_shares_a_card(blue: Path, pins: Path) -> None:
    """A change with no chat has no chat card to match a code against: a shared code would match through the other
    chats' cards, and it would be approved unseen."""
    a = _submit(blue, "exec-nc-a", {"thomas/a.py": "A = 1\n"})
    lone = _no_chat(blue, "exec-nc-b", {"thomas/b.py": "B = 1\n"})
    c = _submit(blue, "exec-nc-c", {"thomas/c.py": "C = 1\n"})

    chain, done = _form(_promoter(blue, pins, Asker()))

    assert _names(chain) == [a.name, c.name] and done == []
    assert _waiting(lone)


def test_a_change_asked_alone_is_never_shared_again_even_under_a_new_sid(blue: Path, pins: Path) -> None:
    first = _submit(blue, "exec-asked-alone", {"thomas/fix_me.py": "VALUE = 2\n"})
    promoter = _promoter(blue, pins, Asker(False))
    assert promoter.promote(first).status == "declined"
    assert _outbox(first.name, "verdict")["card"] == {}, "a single card's verdict names no shared card"
    a = _submit(blue, "exec-other-a", {"thomas/a.py": "A = 1\n"})
    again = _submit(blue, "exec-asked-alone-again", {"thomas/fix_me.py": "VALUE = 2\n"})
    c = _submit(blue, "exec-other-c", {"thomas/c.py": "C = 1\n"})
    assert hashlib.sha256((again / "change.patch").read_bytes()).hexdigest() in promoter._alone, "the same bytes"

    chain, done = _form(promoter)

    assert _names(chain) == [a.name, c.name] and done == []
    assert _waiting(again)


def test_a_change_that_clashes_only_with_one_ahead_of_it_waits(blue: Path, pins: Path) -> None:
    """It must not be refused for someone else's change, which you may yet decline."""
    a = _submit(blue, "exec-clash-a", {"thomas/fix_me.py": "VALUE = 2\n"})
    b = _submit(blue, "exec-clash-b", {"thomas/fix_me.py": "VALUE = 3\n"})
    c = _submit(blue, "exec-clash-c", {"thomas/c.py": "C = 1\n"})

    chain, done = _form(_promoter(blue, pins, Asker()))

    assert _names(chain) == [a.name, c.name] and done == []
    assert _waiting(b)


def test_a_change_that_fails_its_own_check_is_refused_and_the_rest_share(blue: Path, pins: Path) -> None:
    a = _submit(blue, "exec-own-a", {"thomas/a.py": "A = 1\n"})
    broken = _submit(blue, "exec-own-b", {"thomas/b.py": "def broken(:\n"})
    c = _submit(blue, "exec-own-c", {"thomas/c.py": "C = 1\n"})

    chain, done = _form(_promoter(blue, pins, Asker()))

    assert _names(chain) == [a.name, c.name]
    [refused] = done
    assert refused.status == "refused" and refused.detail.startswith("thomas/b.py does not compile"), refused
    assert _outbox(broken.name, "verdict")["status"] == "refused" and not broken.exists()


def test_a_change_dev_moved_under_is_refused_with_every_file_that_stops_it(blue: Path, pins: Path) -> None:
    """Judged by itself on dev it no longer applies: refused as it would be alone, with the files that stop it named,
    so the team sent to repair it can see what to merge."""
    a = _submit(blue, "exec-moved-a", {"thomas/a.py": "A = 1\n"})
    stale = _submit(blue, "exec-moved-b", {"thomas/fix_me.py": "VALUE = 2\n"})
    c = _submit(blue, "exec-moved-c", {"thomas/c.py": "C = 1\n"})
    (blue / "thomas" / "fix_me.py").write_text("VALUE = 'moved on'\n", encoding="utf-8")
    git(blue, "commit", "-qam", "dev moves on under it")

    chain, done = _form(_promoter(blue, pins, Asker()))

    assert _names(chain) == [a.name, c.name]
    [refused] = done
    assert refused.status == "refused" and refused.detail.startswith("the change no longer applies to dev"), refused
    assert refused.conflicts == ["thomas/fix_me.py"]
    assert _outbox(stale.name, "verdict")["conflicts"] == ["thomas/fix_me.py"]


def test_uncommitted_work_refuses_only_the_change_it_is_in(blue: Path, pins: Path) -> None:
    a = _submit(blue, "exec-dirty-a", {"thomas/a.py": "A = 1\n"})
    b = _submit(blue, "exec-dirty-b", {"thomas/fix_me.py": "VALUE = 2\n"})
    c = _submit(blue, "exec-dirty-c", {"thomas/c.py": "C = 1\n"})
    (blue / "thomas" / "fix_me.py").write_text("VALUE = 'someone is editing this'\n", encoding="utf-8")

    chain, done = _form(_promoter(blue, pins, Asker()))

    assert _names(chain) == [a.name, c.name]
    [refused] = done
    assert refused.status == "refused" and refused.detail == RUNNING_COPY_DIRTY + "thomas/fix_me.py", refused
    assert not b.exists(), "the server hands it in again once the work is committed"
    assert "someone is editing" in (blue / "thomas" / "fix_me.py").read_text(encoding="utf-8")


def test_a_check_that_breaks_on_one_member_is_that_members_error(
    blue: Path, pins: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _submit(blue, "exec-break-a", {"thomas/a.py": "A = 1\n"})
    b = _submit(blue, "exec-break-b", {"thomas/b.py": "B = 1\n"})
    c = _submit(blue, "exec-break-c", {"thomas/c.py": "C = 1\n"})
    real = checks.import_break_refusal

    def breaks_on_a(repo, parent, tree, changes):  # noqa: ANN001, ANN202 - as import_break_refusal
        if any(path == "thomas/a.py" for _, path in changes):
            raise KeyError("a check broke")
        return real(repo, parent, tree, changes)

    monkeypatch.setattr(checks, "import_break_refusal", breaks_on_a)

    chain, done = _form(_promoter(blue, pins, Asker()))

    assert _names(chain) == [b.name, c.name]
    [broke] = done
    assert broke.status == "error" and "KeyError" in broke.detail, broke
    assert _outbox(first.name, "verdict")["status"] == "error" and not first.exists()


@pytest.mark.parametrize(
    ("count", "files_each", "fit"), [(6, 1, 5), (3, 9, 2)], ids=["six small changes", "three of nine code files"]
)
def test_a_card_holds_at_most_five_and_only_what_fits(
    blue: Path, pins: Path, count: int, files_each: int, fit: int
) -> None:
    subs = [
        _submit(blue, f"exec-fit-{k}", {f"thomas/pkg_{k}{n}/module_{n}.py": "N = 1\n" for n in range(files_each)})
        for k in range(count)
    ]

    chain, done = _form(_promoter(blue, pins, Asker()))

    assert _names(chain) == [sub.name for sub in subs[:fit]] and done == []
    assert all(_waiting(sub) for sub in subs), "the rest wait for the next card"


def test_at_most_eleven_hand_ins_are_looked_at_in_one_pass(
    blue: Path, pins: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    read: list[str] = []

    def reading(sub_dir: Path) -> tuple[dict[str, str], bytes]:
        read.append(sub_dir.name)
        raise checks.Refused("not read in this test")

    monkeypatch.setattr(checks, "read_submission", reading)
    subs = [cage_shell.cage_root() / "inbox" / f"self-exec-many-{n:02d}" for n in range(12)]

    assert card_chain.open_members(_promoter(blue, pins, Asker()), subs, []) == []
    assert read == [sub.name for sub in subs[: 1 + card_chain.CANDIDATES]] and len(read) == 11
