"""Cancel and a sign-in Windows did not accept are told apart.

Until 2026-10-09 the one prompt call answered True or False, so a mistyped PIN, a prompt that could not be shown and
your Cancel all came back as one False -- and the self-change promoter recorded each of them as you declining the
change (scripts/breakglass_auth.py sets ``cancelled`` only for ERROR_CANCELLED). ``sign_in_answer`` keeps the three
apart; ``verified_sign_in`` still answers True only for an accepted sign-in, for every other caller.

The real Windows prompt is never shown here: the prompt function is replaced in ``sys.modules``.
"""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass

import pytest

from thomas.tools import windows_auth


@dataclass(frozen=True)
class _Result:
    ok: bool
    message: str = ""
    cancelled: bool = False


def _prompt_answers(monkeypatch: pytest.MonkeyPatch, answer: object) -> list[str]:
    shown: list[str] = []

    def prompt(*, prompt_caption: str, prompt_message: str) -> object:
        shown.append(f"{prompt_caption}|{prompt_message}")
        if isinstance(answer, BaseException):
            raise answer
        return answer

    fake = types.ModuleType("scripts.breakglass_auth")
    fake._run_windows_credential_prompt = prompt  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "scripts.breakglass_auth", fake)
    monkeypatch.setattr(windows_auth.platform, "system", lambda: "Windows")
    return shown


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        (_Result(ok=True), "approved"),
        (_Result(ok=False, cancelled=True, message="breakglass authorization cancelled by user"), "cancelled"),
        (_Result(ok=False, message="Windows sign-in was not accepted"), "failed"),
        (OSError("the prompt could not be shown"), "failed"),
        (RuntimeError("no current user"), "failed"),
        (object(), "failed"),
    ],
)
def test_cancel_and_a_sign_in_windows_did_not_accept_are_told_apart(
    monkeypatch: pytest.MonkeyPatch, answer: object, expected: str
) -> None:
    shown = _prompt_answers(monkeypatch, answer)

    assert windows_auth.sign_in_answer("Do the thing", "Pairing code ABC-DEF.") == expected
    assert shown == ["Thomas|Do the thing\n\nPairing code ABC-DEF."], "Windows' own prompt, captioned Thomas"
    assert windows_auth.verified_sign_in("Do the thing", "Pairing code ABC-DEF.") is (expected == "approved")


def test_off_windows_nothing_is_asked_and_nothing_is_a_no_from_you(monkeypatch: pytest.MonkeyPatch) -> None:
    shown = _prompt_answers(monkeypatch, _Result(ok=True))
    monkeypatch.setattr(windows_auth.platform, "system", lambda: "Linux")

    assert windows_auth.sign_in_answer("Do the thing", "why") == "failed"
    assert windows_auth.verified_sign_in("Do the thing", "why") is False
    assert shown == []


def test_a_missing_prompt_is_a_failure_not_a_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "scripts.breakglass_auth", None)  # import raises ImportError
    monkeypatch.setattr(windows_auth.platform, "system", lambda: "Windows")

    assert windows_auth.sign_in_answer("Do the thing", "why") == "failed"
    assert windows_auth.verified_sign_in("Do the thing", "why") is False


def test_the_promoter_asks_through_the_answer_that_tells_them_apart(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.cage import self_change_promoter as sp

    _prompt_answers(monkeypatch, _Result(ok=False, cancelled=False))
    assert sp._windows_sign_in("Do the thing", "why") == "failed"
    _prompt_answers(monkeypatch, _Result(ok=False, cancelled=True))
    assert sp._windows_sign_in("Do the thing", "why") == "cancelled"
