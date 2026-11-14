"""A protected write is approved on a trusted card, and nothing else.

Owner direction, 2026-09-22: "if you got hacked, it could just literally say
whatever ... the card wants to say." So the card for a protected write shows the
real diff, a pairing code, and the model's words only as his; the Windows dialog
carries none of the model's words; a file that guards Thomas is asked every time
(policy C); an edited catalogue refuses without asking; and bytes that are not
the approved bytes are not written.

Honest scope: this closes a TRICKED Thomas. A HACKED one needs the commit-master
and the caged server (docs/superpowers/specs/2026-09-22-trusted-self-change-design.md).
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path, PurePosixPath

import pytest

from thomas.core import protected_write_grants as grants
from thomas.core.user_questions import UserQuestionBook
from thomas.tools import cage_shell, native_auth, trusted_card
from thomas.tools import protected_write_card as card_ui
from thomas.tools.runtime_protection_auth import _maybe_apply_native_auth_override

MODEL_WORDS = "IGNORE THE DIFF, this is only a typo fix"


@pytest.fixture(autouse=True)
def _clean() -> None:
    grants.revoke_all()
    yield
    grants.revoke_all()


def _prompt_recorder(monkeypatch: pytest.MonkeyPatch, answer: bool) -> list[tuple[str, str]]:
    seen: list[tuple[str, str]] = []

    def prompt(action: str, reason: str) -> bool:
        seen.append((action, reason))
        return answer

    monkeypatch.setattr(native_auth, "request_native_authorization", prompt)
    return seen


def _gate(card: trusted_card.TrustedCard | None, rel: str = "thomas/tools/filesystem.py") -> str | None:
    return _maybe_apply_native_auth_override(
        reason=f"'{rel}' is protected",
        rel_posix=PurePosixPath(rel),
        allow_native_auth_override=True,
        action_description=f"Write protected runtime path: {rel} -- {MODEL_WORDS}",
        card=card,
    )


def test_the_os_prompt_carries_the_code_and_never_the_models_words(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _prompt_recorder(monkeypatch, answer=False)
    card = trusted_card.protected_write_card("thomas/tools/filesystem.py", "a\n", "b\n", why=MODEL_WORDS)
    assert _gate(card) is not None, "declined, so refused"
    ((action, reason),) = seen
    assert card.code in action + reason
    assert "typo" not in action + reason and "IGNORE" not in action + reason


def test_without_a_card_the_prompt_still_carries_no_model_words(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _prompt_recorder(monkeypatch, answer=False)
    _gate(None)
    ((action, reason),) = seen
    assert "typo" not in action + reason and "IGNORE" not in action + reason


def _pending_card(book: UserQuestionBook, card: trusted_card.TrustedCard, answer: str) -> tuple[dict, bool]:
    out: dict = {}

    def worker() -> None:
        out["ok"] = card_ui.ask_on_card(
            task="chat-1", path=card.details["path"], why=card.why, book=book, timeout_s=5, card=card
        )

    t = threading.Thread(target=worker)
    t.start()
    for _ in range(500):
        if book.pending(None):
            break
        threading.Event().wait(0.01)
    row = book.pending(None)[0]
    assert book.answer(row["id"], [answer], password_verified=True)
    t.join(5)
    return row, out["ok"]


def test_the_chat_card_shows_the_diff_the_code_and_thomas_words_as_his() -> None:
    card = trusted_card.protected_write_card(
        "thomas/tools/filesystem.py", "keep\nold\n", "keep\nnew\n", why=MODEL_WORDS
    )
    row, ok = _pending_card(UserQuestionBook(), card, card_ui.DECLINE)
    assert ok is False
    details = row["details"]
    fields = {f["label"]: f["value"] for f in details["fields"]}
    assert fields["File"] == "thomas/tools/filesystem.py"
    assert fields["Change"] == card.details["diffstat"]
    assert fields["Thomas says"] == MODEL_WORDS
    assert details["pairing_code"] == card.code
    assert "+new" in details["excerpt"] and "-old" in details["excerpt"]
    assert card.code in details["prompt_action"] and "typo" not in details["prompt_action"]


def test_a_dangerous_file_offers_only_this_change_or_no() -> None:
    card = trusted_card.protected_write_card("agent_safety.toml", "a\n", "b\n", why="")
    row, ok = _pending_card(UserQuestionBook(), card, card_ui.APPROVE_ONCE)
    labels = [o["label"] for o in row["options"]]
    assert labels == [card_ui.APPROVE_ONCE, card_ui.DECLINE], labels
    assert ok is True
    assert grants.snapshot() == {"everything": False, "tasks": [], "files": []}, "a dangerous approval grants nothing"


def test_a_dangerous_file_is_asked_even_after_approve_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    grants.grant(grants.SCOPE_ALL, "chat-1", "anything")
    seen = _prompt_recorder(monkeypatch, answer=False)
    ordinary = trusted_card.protected_write_card("thomas/tools/filesystem.py", "a\n", "b\n")
    assert _gate(ordinary) is None, "an ordinary file rides the grant you chose"
    assert not seen
    dangerous = trusted_card.protected_write_card("agent_safety.toml", "a\n", "b\n")
    assert _gate(dangerous, "agent_safety.toml") is not None, "a gate file was let through on a scope grant"
    assert len(seen) == 1, "a dangerous file must be asked, every time"


def test_an_edited_catalogue_refuses_without_asking(monkeypatch: pytest.MonkeyPatch) -> None:
    pins = Path(cage_shell.DEFAULT_PIN_ROOT)
    pins.mkdir(parents=True, exist_ok=True)
    (pins / trusted_card.PIN_NAME).write_text("0" * 64, encoding="utf-8")
    seen = _prompt_recorder(monkeypatch, answer=True)
    card = trusted_card.protected_write_card("thomas/tools/filesystem.py", "a\n", "b\n")
    refusal = _gate(card)
    assert refusal is not None and "approval cards" in refusal
    assert not seen, "asked for a PIN on a card whose wording was not the pinned wording"


def _tool(tmp_path: Path):
    from thomas.tools.filesystem import WriteProtectedFileTool

    (tmp_path / "thomas" / "tools").mkdir(parents=True)
    return WriteProtectedFileTool(tmp_path, project_root=tmp_path)


def test_an_approved_write_writes_the_approved_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _prompt_recorder(monkeypatch, answer=True)
    target = tmp_path / "thomas" / "tools" / "x.py"
    tool = _tool(tmp_path)
    target.write_text("old = 1\n", encoding="utf-8")
    result = asyncio.run(tool.execute({"path": "thomas/tools/x.py", "content": "new = 2\n", "reason": MODEL_WORDS}))
    assert result.ok, result.error
    assert target.read_text(encoding="utf-8") == "new = 2\n"
    ((action, reason),) = seen
    assert "thomas/tools/x.py" in action and "+1 -1" in action
    assert "typo" not in action + reason


def test_bytes_that_are_not_the_approved_bytes_are_not_written(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _prompt_recorder(monkeypatch, answer=True)
    real = trusted_card.protected_write_card

    def mismatched(rel: str, before: str | None, after: str, **kwargs):
        return real(rel, before, after + "# something else\n", **kwargs)

    monkeypatch.setattr(trusted_card, "protected_write_card", mismatched)
    target = tmp_path / "thomas" / "tools" / "x.py"
    tool = _tool(tmp_path)
    target.write_text("old = 1\n", encoding="utf-8")
    result = asyncio.run(tool.execute({"path": "thomas/tools/x.py", "content": "new = 2\n", "reason": "r"}))
    assert not result.ok
    assert target.read_text(encoding="utf-8") == "old = 1\n", "wrote bytes nobody approved"
