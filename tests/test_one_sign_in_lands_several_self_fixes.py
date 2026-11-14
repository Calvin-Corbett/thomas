"""One Windows sign-in lands several waiting self-fixes, each as its own commit, or none of them.

Your decision, 2026-10-08: "Yes, batch cards". When two or more reviewed self-fixes are waiting, the promoter lists up
to five of them on one card worded by the pinned catalogue, one numbered line each (scripts/cage/shared_card.py).
Signing in puts them all into the running Thomas, each as its own commit with its own submission id, moved onto dev in
one compare-and-swap. Cancel on that card declines nothing: each change is then asked on its own card, one per pass,
where Cancel declines just that one. A sign-in Windows does not accept is never a decline. One waiting self-fix gets
today's single card, unchanged.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

from scripts.cage import card_chain
from scripts.cage import self_change_promoter as sp

from tests.green_support import git
from tests.test_a_self_fix_lands_only_when_you_approve import _outbox, _promoter, _submit, blue, pins  # noqa: F401
from tests.test_a_sign_in_windows_did_not_accept_is_asked_again import Answers, Clock, _code
from thomas.server.ratchet import landing
from thomas.server.ratchet.gitrepo import Repo
from thomas.tools import cage_shell, trusted_card

CARDS = trusted_card.load_catalogue()
SHARED = CARDS.LIST_KINDS[card_chain.SHARED].title
SINGLE = CARDS.KINDS["promote_batch"].title
REPO = Path(__file__).resolve().parents[1]


def _two(blue: Path) -> tuple[Path, Path]:
    a = _submit(blue, "exec-two-a", {"thomas/a.py": "A = 1\n"})
    b = _submit(blue, "exec-two-b", {"thomas/b.py": "B = 1\n", "tests/test_b.py": "def test_b():\n    pass\n"})
    return a, b


def _decided(sub: Path) -> bool:
    return (cage_shell.cage_root() / "outbox" / f"{sub.name}.verdict.json").exists()


def _titles(asked: list[tuple[str, str]]) -> list[str]:
    return [action.split("\n", 1)[0] for action, _ in asked]


def _clean(blue: Path) -> bool:
    return subprocess.run(["git", "status", "--porcelain"], cwd=blue, capture_output=True, text=True).stdout == ""


def test_two_waiting_self_fixes_land_on_one_sign_in_as_two_commits(blue: Path, pins: Path) -> None:
    before = git(blue, "rev-parse", "dev")
    a, b = _two(blue)
    ask = Answers("approved")

    outcome = _promoter(blue, pins, ask).run_once()

    assert outcome is not None and outcome.status == "landed", outcome
    assert _titles(ask.asked) == [SHARED], "one sign-in"
    second = git(blue, "rev-parse", "dev")
    first = git(blue, "rev-parse", f"{second}^")
    assert git(blue, "rev-parse", f"{first}^") == before, "old dev, then one commit per change, in the card's order"
    code = _code(ask.asked[0][1])
    for n, (sub, commit, files) in enumerate(
        [(a, first, ["thomas/a.py"]), (b, second, ["tests/test_b.py", "thomas/b.py"])], 1
    ):
        verdict = _outbox(sub.name, "verdict")
        assert verdict["status"] == "landed" and verdict["commit_sha"] == commit and sorted(verdict["files"]) == files
        assert verdict["card"] == {"pairing_code": code, "position": n, "of": 2}
        assert git(blue, "diff-tree", "--no-commit-id", "--name-only", "-r", commit).splitlines() == files
        assert git(blue, "show", "-s", "--format=%(trailers:key=Thomas-Submission-Id,valueonly)", commit) == sub.name
        assert landing.verify_landed(Repo(blue), commit, sub.name) == "", "the ratchet finds each one's own landing"
        said = f"one of them a single card for 2 changes (pairing code {code}) on which this was number {n}."
        assert said in git(blue, "show", "-s", "--format=%B", commit)
        assert not sub.exists() and (cage_shell.cage_root() / "processed" / sub.name).is_dir()
    assert (blue / "thomas" / "a.py").read_text(encoding="utf-8") == "A = 1\n"
    assert (blue / "thomas" / "b.py").read_text(encoding="utf-8") == "B = 1\n"
    assert _clean(blue), "both are in the running copy, and nothing else changed"


def test_the_shared_card_lists_each_change_and_no_model_words(blue: Path, pins: Path) -> None:
    a, b = _two(blue)
    ask = Answers("approved")

    _promoter(blue, pins, ask).run_once()

    [(action, reason)] = ask.asked
    assert action.split("\n") == [
        SHARED,
        "",
        "Signing in puts these 2 changes into Thomas together. Cancel puts none in and asks about each alone:",
        "1. +1 -0 in 1 file(s): thomas/a.py (new, +1)",
        "2. +3 -0 in 2 file(s): thomas/b.py (new, +1), tests/test_b.py (new, +2)",
    ]
    for words in ("Fixed it.", a.name, b.name, "exec-two"):
        assert words not in action + reason, words
    for n, (sub, mine, theirs) in enumerate([(a, "+A = 1", "B = 1"), (b, "+B = 1", "A = 1")], 1):
        [card] = _outbox(sub.name, "pending")["cards"]
        assert card["kind"] == "promote_several" and card["pairing_code"] == _code(reason)
        assert card["title"] == SHARED and card["body"] == action.split("\n\n", 1)[1]
        assert card["card"] == {"position": n, "of": 2} and card["state"] == "approved"
        assert mine in card["excerpt"] and theirs not in card["excerpt"], "its own diff, which is what lands"
    assert _outbox(b.name, "pending")["cards"][0]["files"] == ["tests/test_b.py (new, +2)", "thomas/b.py (new, +1)"]


def test_cancel_on_a_shared_card_declines_nothing(blue: Path, pins: Path) -> None:
    before = git(blue, "rev-parse", "dev")
    a, b = _two(blue)
    ask = Answers("cancelled", "approved", "cancelled")
    promoter = _promoter(blue, pins, ask)

    first = promoter.run_once()

    assert first is not None and first.status == "landed", first
    assert _titles(ask.asked) == [SHARED, SINGLE] and "thomas/a.py" in ask.asked[1][0], "the first, alone, at once"
    assert b.is_dir() and not _decided(b), "nothing was declined"
    second = promoter.run_once()
    assert second is not None and second.status == "declined" and _titles(ask.asked) == [SHARED, SINGLE, SINGLE]
    assert "thomas/b.py" in ask.asked[2][0]
    assert git(blue, "rev-list", "--count", f"{before}..dev") == "1"
    shared, own = _outbox(a.name, "pending")["cards"]
    assert (shared["kind"], shared["state"]) == ("promote_several", "set aside"), "the shared card stays first"
    assert (own["kind"], own["state"]) == ("promote_batch", "approved")


def test_cancelling_everything_lands_nothing(blue: Path, pins: Path) -> None:
    a, b = _two(blue)
    refs = git(blue, "for-each-ref")
    ask = Answers("cancelled", "cancelled", "cancelled")
    promoter = _promoter(blue, pins, ask)

    promoter.run_once()
    promoter.run_once()

    assert promoter.run_once() is None
    assert git(blue, "for-each-ref") == refs and _clean(blue) and not (blue / "thomas" / "a.py").exists()
    assert _titles(ask.asked) == [SHARED, SINGLE, SINGLE], "declined only on single cards"
    assert [_outbox(sub.name, "verdict")["status"] for sub in (a, b)] == ["declined", "declined"]


def test_a_sign_in_windows_did_not_accept_never_declines_a_shared_card(blue: Path, pins: Path) -> None:
    before = git(blue, "rev-parse", "dev")
    a, b = _two(blue)
    ask = Answers("failed", "failed", "failed")
    promoter = _promoter(blue, pins, ask)
    promoter.clock = clock = Clock()

    outcome = promoter.run_once()

    assert outcome is not None and outcome.status == "held", outcome
    assert _titles(ask.asked) == [SHARED] * 3 and len({_code(reason) for _, reason in ask.asked}) == 1
    assert a.is_dir() and b.is_dir() and not _decided(a) and not _decided(b), "nothing declined, split or left out"
    assert [_outbox(sub.name, "pending")["cards"][-1]["state"] for sub in (a, b)] == ["held", "held"]
    assert git(blue, "rev-parse", "dev") == before
    again = promoter.run_once()
    assert again is not None and again.status == "held" and len(ask.asked) == 3, "inside the pause nothing is asked"

    clock.now += sp._QUIET_S + 1
    ask.answers = ["approved"]
    landed = promoter.run_once()

    assert landed is not None and landed.status == "landed", landed
    assert _titles(ask.asked[3:]) == [SHARED] and _code(ask.asked[3][1]) == _code(ask.asked[0][1]), "the same card"
    assert not a.exists() and not b.exists()


def test_a_failed_sign_in_shows_the_same_shared_card_again_with_the_retry_line(blue: Path, pins: Path) -> None:
    _two(blue)
    ask = Answers("failed", "approved")

    outcome = _promoter(blue, pins, ask).run_once()

    assert outcome is not None and outcome.status == "landed", outcome
    (first_action, first_reason), (second_action, second_reason) = ask.asked
    assert second_action == first_action and first_action.startswith(SHARED)
    assert second_reason == f"{CARDS.RETRY_NOTE}\n\n{first_reason}"


def test_a_lone_self_fix_gets_todays_single_card(blue: Path, pins: Path) -> None:
    _submit(blue, "exec-lone", {"thomas/fix_me.py": "VALUE = 2\n"})
    ask = Answers("approved")

    outcome = _promoter(blue, pins, ask).run_once()

    assert outcome is not None and outcome.status == "landed" and outcome.card == {}, outcome
    [(action, _reason)] = ask.asked
    assert action.startswith(SINGLE + "\n\n") and action.endswith("\nCancel declines this change.")


def test_after_cancel_the_owner_desk_is_served_between_single_cards(blue: Path, pins: Path) -> None:
    """The service loop serves the owner desk between passes (scripts/cage/promoter_service.py): after a Cancel, each
    pass asks one single card, never every one of them in a row."""
    for n in range(3):
        _submit(blue, f"exec-desk-{n}", {f"thomas/m{n}.py": "M = 1\n"})
    ask = Answers("cancelled", "approved", "approved", "approved")
    promoter = _promoter(blue, pins, ask)

    asked_by_pass = []
    for _ in range(3):
        outcome = promoter.run_once()
        assert outcome is not None and outcome.status == "landed", outcome
        asked_by_pass.append(len(ask.asked))

    assert asked_by_pass == [2, 3, 4]
    assert _titles(ask.asked) == [SHARED, SINGLE, SINGLE, SINGLE] and promoter.run_once() is None


def test_changes_set_aside_go_first_in_card_order_and_never_share_again(blue: Path, pins: Path) -> None:
    """After a Cancel, the changes on the card are asked alone before anything else waiting, in the card's order, and
    are never put on a shared card again, even one whose own card was put away after sign-ins that did not go through."""
    a = _submit(blue, "exec-aside-a", {"thomas/fix_me.py": "VALUE = 2\n"})
    _submit(blue, "exec-aside-x", {"thomas/fix_me.py": "VALUE = 3\n"})  # clashes with a: it waits, off the card
    b = _submit(blue, "exec-aside-b", {"thomas/b.py": "B = 1\n"})
    ask = Answers("cancelled", "failed", "failed", "failed", "approved", "approved")
    promoter = _promoter(blue, pins, ask)
    promoter.clock = clock = Clock()

    assert promoter.run_once().status == "held"  # type: ignore[union-attr]
    clock.now += sp._QUIET_S + 1
    assert promoter.run_once().status == "landed" and "thomas/fix_me.py" in ask.asked[4][0], "a, first on the card"
    _submit(blue, "exec-aside-d", {"thomas/d.py": "D = 1\n"})
    assert promoter.run_once().status == "landed"  # type: ignore[union-attr]

    assert _titles(ask.asked) == [SHARED, SINGLE, SINGLE, SINGLE, SINGLE, SINGLE]
    assert "thomas/b.py" in ask.asked[5][0] and not a.exists() and not b.exists()


def test_a_change_set_aside_keeps_its_turn_while_its_own_card_is_held(blue: Path, pins: Path) -> None:
    """Its own card put away after three sign-ins Windows did not accept, a change is still asked before the rest."""
    for x in "abc":
        _submit(blue, f"exec-turn-{x}", {f"thomas/{x}.py": f"{x.upper()} = 1\n"})
    ask = Answers("cancelled", *["failed"] * 3, "approved", *["failed"] * 3, "approved", "approved")
    promoter = _promoter(blue, pins, ask)
    promoter.clock = clock = Clock()

    statuses = []
    for _ in range(5):
        statuses.append(promoter.run_once().status)  # type: ignore[union-attr]
        clock.now += sp._QUIET_S + 1

    whose = ["card" if a.startswith(SHARED) else next(x for x in "abc" if f"/{x}.py" in a) for a, _ in ask.asked]
    assert whose == ["card", "a", "a", "a", "a", "b", "b", "b", "b", "c"], "each in the card's order, held or not"
    assert statuses == ["held", "landed", "held", "landed", "landed"]


def test_a_change_declined_alone_is_never_shared_again(blue: Path, pins: Path) -> None:
    _submit(blue, "exec-declined", {"thomas/fix_me.py": "VALUE = 2\n"})
    ask = Answers("cancelled", "approved", "approved")
    promoter = _promoter(blue, pins, ask)
    assert promoter.run_once().status == "declined"  # type: ignore[union-attr]
    _submit(blue, "exec-declined-again", {"thomas/fix_me.py": "VALUE = 2\n"})  # the same bytes, a new sid
    _submit(blue, "exec-not-declined", {"thomas/a.py": "A = 1\n"})

    assert promoter.run_once().status == "landed"  # type: ignore[union-attr]
    assert promoter.run_once().status == "landed"  # type: ignore[union-attr]

    assert _titles(ask.asked) == [SINGLE, SINGLE, SINGLE], "asked about on its own again, first, never shared"
    assert "thomas/fix_me.py" in ask.asked[1][0] and "thomas/a.py" in ask.asked[2][0]


def test_the_pairing_code_binds_every_tree_their_order_and_dev() -> None:
    def member(sid: str, base: str, tree: str) -> card_chain.Member:
        return card_chain.Member(Path(sid), meta={"id": sid}, base=base, tree=tree)

    def code(dev: str, chain: list[card_chain.Member]) -> str:
        rows = [{"files": [["thomas/x.py", "M", 1, 1]]} for _ in chain]
        _title, _body, details = CARDS.render_list(card_chain.SHARED, rows)
        digest = card_chain.chain_digest(dev, chain)
        return CARDS.pairing_code(card_chain.SHARED, details, digest, f"{card_chain.SHARED}:{dev[:12]}")

    dev, one, two = "1" * 40, "a" * 40, "b" * 40
    shown = code(dev, [member("self-a", dev, one), member("self-b", one, two)])

    assert code(dev, [member("self-a", dev, one), member("self-b", one, two)]) == shown, "equal inputs, equal code"
    assert code(dev, [member("self-b", one, two), member("self-a", dev, one)]) != shown, "their order"
    assert code(dev, [member("self-a", dev, one), member("self-b", one, "c" * 40)]) != shown, "a tree"
    assert code(dev, [member("self-a", dev, one), member("self-c", one, two)]) != shown, "a member"
    assert code("2" * 40, [member("self-a", dev, one), member("self-b", one, two)]) != shown, "dev"
    digest = card_chain.chain_digest(dev, [member("self-a", dev, one)])
    assert digest != card_chain.chain_digest("2" * 40, [member("self-a", dev, one)]), "dev, whatever the nonce"


def test_the_shared_card_never_runs_the_code_it_promotes(blue: Path, pins: Path, tmp_path: Path) -> None:
    marker = tmp_path / "ran.txt"
    code = f"open({str(marker)!r}, 'w').write('ran')\n"
    _submit(blue, "exec-inert-a", {"thomas/side_a.py": code, "tests/test_side_a.py": code})
    _submit(blue, "exec-inert-b", {"thomas/side_b.py": code, "tests/conftest.py": code})
    ask = Answers("approved")

    assert _promoter(blue, pins, ask).run_once().status == "landed"  # type: ignore[union-attr]
    assert _titles(ask.asked) == [SHARED]
    assert not marker.exists()


def test_the_promoter_never_relies_on_assert() -> None:
    """python -O removes every assert: a check that a landing relies on is a plain if and raise."""
    for name in ("self_change_promoter.py", "card_chain.py", "shared_card.py", "shared_landing.py"):
        source = (REPO / "scripts" / "cage" / name).read_text(encoding="utf-8")
        found = [node.lineno for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Assert)]
        assert found == [], f"{name} uses assert on line(s) {found}"
