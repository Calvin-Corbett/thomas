"""A sign-in Windows does not accept is never your answer: the same card comes back, and nothing is declined.

Until 2026-10-09 a mistyped PIN, or a prompt that could not be shown, came back from the one prompt call as False --
the same as Cancel -- and the promoter declined the change on it (scripts/breakglass_auth.py, thomas/tools/
windows_auth.py, self_change_promoter._ask). Now the same card is asked again, with the same pairing code and one line
saying the last answer was not accepted, up to three times. After that nothing is declined and nothing is left out: the
card is put away, the promoter waits two minutes, and the card is asked again.

Every card also says what Cancel does on it, and names its files in full: a 200-character cap hid two of
self-thomas-ea1c748556b8's six files on 2026-10-08 without saying so.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from scripts.cage import self_change_promoter as sp

from tests.green_support import git
from tests.test_a_self_fix_lands_only_when_you_approve import _outbox, _promoter, _submit, blue, pins  # noqa: F401
from thomas.tools import cage_shell, trusted_card

CARDS = trusted_card.load_catalogue()


class Answers:
    """The prompt, answering in turn: "approved", "cancelled", "failed" (or the old True/False)."""

    def __init__(self, *answers: object) -> None:
        self.answers = list(answers)
        self.asked: list[tuple[str, str]] = []

    def __call__(self, action: str, reason: str) -> object:
        self.asked.append((action, reason))
        return self.answers.pop(0) if self.answers else "cancelled"


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _code(reason: str) -> str:
    return reason.split("Pairing code ", 1)[1][:7]


def test_three_sign_ins_windows_did_not_accept_decline_nothing(blue: Path, pins: Path) -> None:
    before = git(blue, "rev-parse", "dev")
    sub = _submit(blue, "exec-typo", {"thomas/fix_me.py": "VALUE = 2\n"})
    ask = Answers("failed", "failed", "failed")
    promoter = _promoter(blue, pins, ask)
    promoter.clock = clock = Clock()

    outcome = promoter.run_once()

    assert outcome is not None and outcome.status == "held", outcome
    assert len(ask.asked) == 3, "the same card, three times"
    assert len({action for action, _ in ask.asked}) == 1 and len({_code(r) for _, r in ask.asked}) == 1
    assert not ask.asked[0][1].startswith(CARDS.RETRY_NOTE)
    assert all(reason.startswith(CARDS.RETRY_NOTE + "\n\n") for _, reason in ask.asked[1:])
    assert sub.is_dir(), "still in the inbox"
    assert not (cage_shell.cage_root() / "outbox" / f"{sub.name}.verdict.json").exists(), "no verdict: not declined"
    assert _outbox(sub.name, "pending")["cards"][-1]["state"] == "held"
    assert git(blue, "rev-parse", "dev") == before

    again = promoter.run_once()  # inside the pause: nothing is asked
    assert again is not None and again.status == "held" and len(ask.asked) == 3

    clock.now += sp._QUIET_S + 1
    ask.answers = ["approved"]
    landed = promoter.run_once()
    assert landed is not None and landed.status == "landed", landed
    assert _code(ask.asked[-1][1]) == _code(ask.asked[0][1]), "the same card when nothing changed"
    assert git(blue, "show", "dev:thomas/fix_me.py") == "VALUE = 2"


def test_a_failed_sign_in_shows_the_same_card_again_with_the_retry_line(blue: Path, pins: Path) -> None:
    sub = _submit(blue, "exec-typo-once", {"thomas/fix_me.py": "VALUE = 2\n"})
    ask = Answers("failed", True)

    outcome = _promoter(blue, pins, ask).promote(sub)

    assert outcome.status == "landed", outcome.detail
    (first_action, first_reason), (second_action, second_reason) = ask.asked
    assert second_action == first_action
    assert second_reason == f"{CARDS.RETRY_NOTE}\n\n{first_reason}"


def test_cancel_still_declines_a_single_card(blue: Path, pins: Path) -> None:
    before = git(blue, "rev-parse", "dev")
    sub = _submit(blue, "exec-cancel", {"thomas/fix_me.py": "VALUE = 2\n"})
    ask = Answers("cancelled")

    outcome = _promoter(blue, pins, ask).promote(sub)

    assert outcome.status == "declined" and len(ask.asked) == 1
    assert git(blue, "rev-parse", "dev") == before
    assert _outbox(sub.name, "verdict")["status"] == "declined"


def test_a_sign_in_not_accepted_on_a_guarded_card_never_leaves_the_file_out(blue: Path, pins: Path) -> None:
    sub = _submit(blue, "exec-guarded-typo", {"scripts/cage/new_rule.py": "RULE = 1\n", "thomas/fix_me.py": "V = 2\n"})
    ask = Answers("failed", "failed", "failed")
    promoter = _promoter(blue, pins, ask)
    promoter.clock = clock = Clock()

    assert promoter.run_once().status == "held"  # type: ignore[union-attr]
    assert all(action.startswith("Change a file that guards Thomas") for action, _ in ask.asked)

    clock.now += sp._QUIET_S + 1
    ask.answers = ["approved", "approved"]
    landed = promoter.run_once()

    assert landed is not None and landed.status == "landed", landed
    assert ask.asked[3][0].startswith("Change a file that guards Thomas"), "the guarded card first, again"
    assert sorted(landed.files) == ["scripts/cage/new_rule.py", "thomas/fix_me.py"], "nothing was left out"


def test_a_prompt_that_cannot_show_is_held_not_declined(blue: Path, pins: Path) -> None:
    """The real prompt answers "failed" when Windows is not there to ask: it must never be read as a no from you."""
    sub = _submit(blue, "exec-no-prompt", {"thomas/fix_me.py": "VALUE = 2\n"})
    promoter = sp.Promoter(repo=blue, cage_root=cage_shell.cage_root(), ask=lambda _a, _r: "failed", pin_root=pins,
                           audit=lambda _r: [])  # fmt: skip

    assert promoter.promote(sub).status == "held"
    assert sub.is_dir()


def test_a_hand_in_taken_aside_after_a_failed_sign_in_is_not_shown_again(blue: Path, pins: Path) -> None:
    """Moved aside to be checked first while its card was up: asked once, never again (2026-09-27: "asked twice")."""
    sub = _submit(blue, "exec-aside-retry", {"thomas/fix_me.py": "VALUE = 2\n"})
    aside = sub.parent.parent / "withdrawn" / sub.name
    asked: list[str] = []

    def fails_then_taken_aside(_action: str, reason: str) -> str:
        asked.append(reason)
        aside.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(sub), str(aside))  # the server moves it aside to be checked first
        return "failed"

    outcome = _promoter(blue, pins, fails_then_taken_aside).promote(sub)

    assert outcome.status == "withdrawn", outcome
    assert len(asked) == 1, "the card was shown again about a hand-in no longer in the inbox"
    assert not (cage_shell.cage_root() / "outbox" / f"{sub.name}.pending.json").exists(), "no card left asking"


def test_a_prompt_that_raises_is_a_sign_in_that_did_not_go_through(blue: Path, pins: Path) -> None:
    """Never your answer, and never a crash that leaves this hand-in first in the inbox for every pass."""
    sub = _submit(blue, "exec-prompt-raises", {"thomas/fix_me.py": "VALUE = 2\n"})
    asked: list[str] = []

    def broken(_action: str, reason: str) -> str:
        asked.append(reason)
        raise LookupError("the prompt broke")

    outcome = _promoter(blue, pins, broken).promote(sub)

    assert outcome.status == "held", outcome
    assert len(asked) == sp._TRIES and sub.is_dir()
    assert _outbox(sub.name, "pending")["cards"][-1]["state"] == "held"


def test_a_card_too_long_for_the_prompt_is_never_shown(blue: Path, pins: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Windows shows at most 1,024 characters of the message (CREDUI_MAX_MESSAGE_LENGTH) and cuts the rest."""
    sub = _submit(blue, "exec-too-long", {"thomas/fix_me.py": "VALUE = 2\n"})
    monkeypatch.setattr(CARDS, "DIALOG_LIMIT", 120)
    ask = Answers("approved")

    outcome = _promoter(blue, pins, ask).promote(sub)

    assert outcome.status == "error" and "would not fit" in outcome.detail, outcome.detail
    assert ask.asked == []


# -- what the single card says ----------------------------------------------------------------------------------- #

EA1C_LIKE = {
    "thomas/server/chat_app_keys.py": "KEYS = 1\n" * 26,
    "thomas/server/routes/chat_v2_keys.py": "V = 2\n",
    "thomas/server/app_chat_store.py": "S = 1\n",
    "thomas/server/worker_runtime.py": "W = 1\n",
    "tests/test_the_server_core_imports_no_route_module.py": "T = 1\n" * 33,
    "changelog.d/chat-keys-live-outside-routes.md": "note\n" * 4,
}


def test_the_single_card_names_every_file_and_what_cancel_does(blue: Path, pins: Path) -> None:
    sub = _submit(blue, "exec-six-files", EA1C_LIKE)
    ask = Answers("approved")

    outcome = _promoter(blue, pins, ask).promote(sub)

    assert outcome.status == "landed", outcome.detail
    action = ask.asked[0][0]
    for path in EA1C_LIKE:
        assert path in action, path
    assert "..." not in action and " more" not in action
    assert action.endswith("\nCancel declines this change.")
    assert "thomas/server/chat_app_keys.py (new, +26)" in action


def test_the_guarded_card_says_cancel_leaves_only_that_file_out(blue: Path, pins: Path) -> None:
    sub = _submit(blue, "exec-guarded-words", {"scripts/cage/new_rule.py": "RULE = 1\n", "thomas/fix_me.py": "V = 2\n"})
    ask = Answers("cancelled", "approved")

    outcome = _promoter(blue, pins, ask).promote(sub)

    assert outcome.status == "landed" and outcome.files == ["thomas/fix_me.py"], outcome
    assert ask.asked[0][0].endswith("\nCancel leaves this file out; any other file in its change is still asked.")
    assert ask.asked[1][0].endswith("\nCancel declines this change.")
