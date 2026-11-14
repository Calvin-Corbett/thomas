"""A path given by its last folders names the committed file it ends with, not a new file at the root.

On 2026-09-27 a repair round for the ChatGPT sign-in project said a test's failing assertion was about "a status call
that moved to js/chat_model_accounts.js". The file is thomas/server/web/js/chat_model_accounts.js; the contract looked
for the name only three folders deep, found nothing, and made `js/chat_model_accounts.js` at the root of the copy a
file the task must create. The team wrote an 18-line stand-in there ("this file is not a second UI entry point") to
satisfy it, and handed that in. A path with a folder in it that is not at the root now resolves to the one committed
file whose path ends with it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from thomas.core.acceptance_contract import build_contract

DEEP = "thomas/server/web/js/chat_model_accounts.js"


def _git(ws: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=ws, check=True, capture_output=True)


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    for rel in (DEEP, "thomas/server/web/index.html"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("// the page's own module\n", encoding="utf-8")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path


def _ids(text: str, ws: Path) -> list[str]:
    return [item.item_id for item in build_contract(text, ws)]


def test_a_path_that_ends_a_committed_file_is_that_file(ws: Path) -> None:
    text = (
        "Put tests/test_openai_codex_oauth.py back exactly as dev has it. Its failing assertion is a dev failure about "
        "a status call that moved to js/chat_model_accounts.js, not part of your task."
    )

    assert not [i for i in _ids(text, ws) if "chat_model_accounts" in i]


def test_a_new_file_the_task_names_is_still_an_output(ws: Path) -> None:
    assert "output:notes/signin.md" in _ids("Write the change up in notes/signin.md.", ws)


def test_a_tail_two_committed_files_share_is_not_guessed(ws: Path) -> None:
    other = ws / "apps" / "site" / "js" / "chat_model_accounts.js"
    other.parent.mkdir(parents=True)
    other.write_text("// another\n", encoding="utf-8")
    _git(ws, "add", "-A")
    _git(ws, "commit", "-q", "-m", "a second file with the same tail")

    assert "output:js/chat_model_accounts.js" in _ids("Create js/chat_model_accounts.js.", ws)
