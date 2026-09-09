"""Plain `thomas chat` can use the ChatGPT sign-in the server has.

2026-09-05: `python -m thomas chat "..."` failed in every shell with "ChatGPT
OAuth is not connected" because only the server's OAuth module registers the
token resolver and the CLI never imported it. The entry module now registers
it before the commands that talk to a model.
"""

from __future__ import annotations

import pytest

from thomas.cli import main as cli_main
from thomas.core import codex_auth


@pytest.mark.parametrize("command", ["chat", "repl", "agent"])
def test_model_commands_register_the_chatgpt_resolver(command: str, monkeypatch) -> None:
    monkeypatch.setattr(codex_auth, "_access_token_resolver", None)

    assert cli_main._register_transport_signins([command, "hello"]) is True
    assert codex_auth._access_token_resolver is not None


@pytest.mark.parametrize("argv", [["status"], ["cron", "list"], [], ["--help"]])
def test_other_commands_do_not_pay_for_the_server_import(argv, monkeypatch) -> None:
    monkeypatch.setattr(codex_auth, "_access_token_resolver", None)

    assert cli_main._register_transport_signins(argv) is False
    assert codex_auth._access_token_resolver is None
